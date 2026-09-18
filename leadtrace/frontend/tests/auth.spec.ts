import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createApp, h } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";
import { z } from "zod";

import { apiRequest } from "../src/api/client";
import LoginPage from "../src/auth/LoginPage.vue";
import ChangePasswordPage from "../src/auth/ChangePasswordPage.vue";
import AppShell from "../src/app/AppShell.vue";
import { useAuthStore } from "../src/auth/store";
import { createAppRouter } from "../src/app/router";
import { zhCN } from "../src/i18n/zh-CN";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      "X-Request-ID": "frontend-auth-request",
    },
  });
}

class AuthBroadcastChannel extends EventTarget {
  static readonly sent: unknown[] = [];
  static readonly instances: AuthBroadcastChannel[] = [];
  closed = false;

  constructor() {
    super();
    AuthBroadcastChannel.instances.push(this);
  }

  postMessage(message: unknown): void {
    AuthBroadcastChannel.sent.push(message);
  }

  close(): void {
    this.closed = true;
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((finish) => {
    resolve = finish;
  });
  return { promise, resolve };
}

const reviewerSession = {
  user: { username: "reviewer", display_name: "Reviewer", role: "reviewer" as const, must_change_password: false },
  csrf_token: "reviewer-csrf",
};

const adminSession = {
  user: { username: "admin", display_name: "Admin", role: "admin" as const, must_change_password: false },
  csrf_token: "admin-csrf",
};

describe("authenticated login flow", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    AuthBroadcastChannel.sent.length = 0;
    AuthBroadcastChannel.instances.length = 0;
  });

  afterEach(() => {
    useAuthStore().stopSessionSync();
    vi.unstubAllGlobals();
  });

  it("uses the shared authentication and form primitives", async () => {
    const router = createAppRouter(createMemoryHistory());
    await router.push("/login");
    await router.isReady();
    const login = mount(LoginPage, { global: { plugins: [router] } });

    expect(login.get("main").classes()).toContain("auth-shell");
    expect(login.get("form").classes()).toContain("auth-panel");
    expect(login.findAll(".form-field")).toHaveLength(2);

    const password = mount(ChangePasswordPage, { global: { plugins: [router] } });
    expect(password.get("main").classes()).toContain("auth-shell");
    expect(password.get("form").classes()).toContain("auth-panel");
    expect(password.findAll(".form-field")).toHaveLength(3);
  });

  it("shows one generic login error without revealing account state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(401, {
        code: "AUTHENTICATION_REQUIRED",
        message: "backend detail must not be rendered",
        details: {},
        request_id: "frontend-auth-request",
      })),
    );
    const router = createAppRouter(createMemoryHistory());
    await router.push("/login");
    await router.isReady();
    const wrapper = mount(LoginPage, {
      global: { plugins: [router] },
    });

    await wrapper.get("#username").setValue("disabled.or.missing");
    await wrapper.get("#password").setValue("wrong password");
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(wrapper.get("[role='alert']").text()).toBe("用户名或密码错误，请重试。");
    expect(wrapper.text()).not.toContain("disabled.or.missing");
    expect(wrapper.text()).not.toContain("backend detail");
    expect(wrapper.get("#username").attributes("autocomplete")).toBe("username");
    expect(wrapper.get("#password").attributes("autocomplete")).toBe(
      "current-password",
    );
  });

  it("routes legacy flagged accounts into the normal application", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(200, {
        user: {
          username: "reviewer.one",
          display_name: "Reviewer One",
          role: "reviewer",
          must_change_password: true,
        },
        csrf_token: "csrf-value",
      })),
    );
    const router = createAppRouter(createMemoryHistory());
    await router.push("/login");
    await router.isReady();
    const wrapper = mount(LoginPage, {
      global: { plugins: [router] },
    });

    await wrapper.get("#username").setValue("reviewer.one");
    await wrapper.get("#password").setValue("Initial password 2026!");
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/papers");
    expect(useAuthStore().user?.role).toBe("reviewer");
    expect(wrapper.text()).not.toContain("修改密码");
  });

  it("publishes credential changes only after login, password rotation, and logout settle", async () => {
    let finishLogin: ((response: Response) => void) | undefined;
    const loginResponse = new Promise<Response>((resolve) => {
      finishLogin = resolve;
    });
    vi.stubGlobal("BroadcastChannel", AuthBroadcastChannel);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/auth/login") return loginResponse;
      if (path === "/api/v1/auth/password") {
        return jsonResponse(200, {
          user: { username: "reviewer", display_name: "Reviewer", role: "reviewer", must_change_password: false },
          csrf_token: "password-csrf",
        });
      }
      if (path === "/api/v1/auth/logout") return new Response(null, { status: 204 });
      throw new Error(`Unexpected request: ${path}`);
    }));
    createAppRouter(createMemoryHistory());
    const auth = useAuthStore();

    const login = auth.login("reviewer", "password");
    expect(AuthBroadcastChannel.sent).toEqual([]);
    finishLogin?.(jsonResponse(200, {
      user: { username: "reviewer", display_name: "Reviewer", role: "reviewer", must_change_password: false },
      csrf_token: "login-csrf",
    }));
    await login;
    expect(AuthBroadcastChannel.sent).toEqual([{ kind: "credentials-changed", version: 1 }]);

    await auth.changePassword("password", "new password");
    expect(AuthBroadcastChannel.sent).toHaveLength(2);

    await auth.logout();
    expect(AuthBroadcastChannel.sent).toHaveLength(3);
  });

  it("allows the browser to submit simple passwords from six characters", async () => {
    const router = createAppRouter(createMemoryHistory());
    const wrapper = mount(ChangePasswordPage, {
      global: { plugins: [router] },
    });

    expect(wrapper.get("#new-password").attributes("minlength")).toBe("6");
    expect(wrapper.get("#confirm-password").attributes("minlength")).toBe("6");
  });

  it("returns an expired protected session to login with its destination", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(401, {
        code: "AUTHENTICATION_REQUIRED",
        message: "Authentication required",
        details: {},
        request_id: "frontend-auth-request",
      })),
    );
    const router = createAppRouter(createMemoryHistory());

    await router.push("/papers?page=2&target=kinase");
    await router.isReady();

    expect(router.currentRoute.value.path).toBe("/login");
    expect(router.currentRoute.value.query.redirect).toBe(
      "/papers?page=2&target=kinase",
    );
    expect(useAuthStore().user).toBeNull();
  });

  it("deduplicates concurrent forced session refreshes", async () => {
    let finishRefresh: ((response: Response) => void) | undefined;
    const refreshResponse = new Promise<Response>((resolve) => {
      finishRefresh = resolve;
    });
    const fetch = vi.fn(() => refreshResponse);
    vi.stubGlobal("fetch", fetch);
    const auth = useAuthStore();
    auth.acceptSession({
      user: { username: "reviewer", display_name: "Reviewer", role: "reviewer", must_change_password: false },
      csrf_token: "reviewer-csrf",
    });

    const focusRefresh = auth.refreshSession();
    const visibilityRefresh = auth.refreshSession();
    expect(fetch).toHaveBeenCalledOnce();
    finishRefresh?.(jsonResponse(200, {
      user: { username: "admin", display_name: "Admin", role: "admin", must_change_password: false },
      csrf_token: "admin-csrf",
    }));
    await Promise.all([focusRefresh, visibilityRefresh]);

    expect(auth.user?.role).toBe("admin");
    expect(auth.csrfToken).toBe("admin-csrf");
  });

  it.each([
    ["200", () => jsonResponse(200, reviewerSession)],
    ["401", () => jsonResponse(401, {
      code: "AUTHENTICATION_REQUIRED",
      message: "Authentication required",
      details: {},
      request_id: "stale-refresh",
    })],
  ])("does not let an old refresh %s overwrite a completed login", async (_status, oldResponse) => {
    const oldRefresh = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/auth/session") return oldRefresh.promise;
      if (path === "/api/v1/auth/login") return jsonResponse(200, adminSession);
      throw new Error(`Unexpected request: ${path}`);
    }));
    const auth = useAuthStore();
    auth.acceptSession(reviewerSession);

    const refresh = auth.refreshSession();
    await expect(auth.login("admin", "password")).resolves.toBe(true);
    oldRefresh.resolve(oldResponse());
    await refresh;

    expect(auth.user?.username).toBe("admin");
    expect(auth.csrfToken).toBe("admin-csrf");
  });

  it("lets login settle before consuming a queued plain refresh", async () => {
    const loginResponse = deferred<Response>();
    let sessionReads = 0;
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/auth/login") return loginResponse.promise;
      if (path === "/api/v1/auth/session") {
        sessionReads += 1;
        return jsonResponse(401, {
          code: "AUTHENTICATION_REQUIRED",
          message: "Authentication required",
          details: {},
          request_id: "refresh-during-login",
        });
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetch);
    const auth = useAuthStore();
    auth.acceptSession(reviewerSession);

    const login = auth.login("admin", "password");
    await auth.refreshSession();
    loginResponse.resolve(jsonResponse(200, adminSession));

    await expect(login).resolves.toBe(true);
    await flushPromises();

    expect(sessionReads).toBe(1);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(auth.user).toBeNull();
    expect(auth.csrfToken).toBeNull();
    expect(auth.sessionNotice).toBeNull();
  });

  it("refreshes after login when a cross-tab session signal arrives during the mutation", async () => {
    const loginResponse = deferred<Response>();
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/auth/login") return loginResponse.promise;
      if (path === "/api/v1/auth/session") return jsonResponse(200, adminSession);
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetch);
    const auth = useAuthStore();
    auth.acceptSession(reviewerSession);

    const login = auth.login("reviewer", "password");
    await auth.refreshSession({ sessionChanged: true });
    expect(fetch).toHaveBeenCalledOnce();

    loginResponse.resolve(jsonResponse(200, reviewerSession));
    await expect(login).resolves.toBe(true);
    await flushPromises();

    expect(fetch).toHaveBeenCalledTimes(2);
    expect(auth.user?.username).toBe("admin");
    expect(auth.sessionNotice).toBe(zhCN.auth.sessionChanged);
  });

  it("keeps a login mutation authoritative when an unrelated request returns 401", async () => {
    const loginResponse = deferred<Response>();
    let sessionReads = 0;
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/auth/login") return loginResponse.promise;
      if (path === "/api/v2/unrelated-read") {
        return jsonResponse(401, {
          code: "AUTHENTICATION_REQUIRED",
          message: "Authentication required",
          details: {},
          request_id: "unrelated-unauthorized",
        });
      }
      if (path === "/api/v1/auth/session") {
        sessionReads += 1;
        return jsonResponse(200, adminSession);
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetch);
    const auth = useAuthStore();
    auth.acceptSession(reviewerSession);
    createAppRouter(createMemoryHistory());

    const login = auth.login("admin", "password");
    const unrelatedFailure = await apiRequest(
      "/api/v2/unrelated-read",
      z.unknown(),
    ).catch((error: unknown) => error);
    const mutationLockStayedActive = auth.credentialMutationInProgress;
    loginResponse.resolve(jsonResponse(200, adminSession));
    const loginSucceeded = await login;
    await flushPromises();

    expect(unrelatedFailure).toMatchObject({
      code: "AUTHENTICATION_REQUIRED",
      requestId: "unrelated-unauthorized",
    });
    expect(mutationLockStayedActive).toBe(true);
    expect(loginSucceeded).toBe(true);
    expect(sessionReads).toBe(1);
    expect(auth.user?.username).toBe("admin");
    expect(auth.csrfToken).toBe("admin-csrf");
    expect(auth.sessionNotice).toBeNull();
  });

  it.each([
    ["204", () => new Response(null, { status: 204 })],
    ["401", () => jsonResponse(401, {
      code: "AUTHENTICATION_REQUIRED",
      message: "Authentication required",
      details: {},
      request_id: "logout-raced-with-other-tab",
    })],
  ])("refreshes the authoritative session after logout %s when another tab changed credentials", async (_status, logoutResult) => {
    const logoutResponse = deferred<Response>();
    let sessionReads = 0;
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/auth/logout") return logoutResponse.promise;
      if (path === "/api/v1/auth/session") {
        sessionReads += 1;
        return jsonResponse(200, adminSession);
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetch);
    const auth = useAuthStore();
    auth.acceptSession(reviewerSession);

    const logout = auth.logout();
    await auth.refreshSession({ sessionChanged: true });
    expect(fetch).toHaveBeenCalledOnce();
    logoutResponse.resolve(logoutResult());
    await logout;
    await flushPromises();

    expect(sessionReads).toBe(1);
    expect(auth.user?.username).toBe("admin");
    expect(auth.csrfToken).toBe("admin-csrf");
    expect(auth.sessionNotice).toBe(zhCN.auth.sessionChanged);
  });

  it("queues a plain refresh during a failed mutation without showing a cross-tab notice", async () => {
    const loginResponse = deferred<Response>();
    let sessionReads = 0;
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/auth/login") return loginResponse.promise;
      if (path === "/api/v1/auth/session") {
        sessionReads += 1;
        return jsonResponse(200, adminSession);
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetch);
    const auth = useAuthStore();
    auth.acceptSession(reviewerSession);

    const login = auth.login("admin", "password");
    await auth.refreshSession();
    expect(fetch).toHaveBeenCalledOnce();
    loginResponse.resolve(jsonResponse(503, {
      code: "SERVICE_UNAVAILABLE",
      message: "Temporarily unavailable",
      details: {},
      request_id: "login-unavailable",
    }));
    await expect(login).resolves.toBe(false);
    await flushPromises();

    expect(sessionReads).toBe(1);
    expect(auth.user?.username).toBe("admin");
    expect(auth.csrfToken).toBe("admin-csrf");
    expect(auth.sessionNotice).toBeNull();
  });

  it("does not let an old refresh overwrite a completed password rotation", async () => {
    const oldRefresh = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/auth/session") return oldRefresh.promise;
      if (path === "/api/v1/auth/password") {
        return jsonResponse(200, { ...reviewerSession, csrf_token: "rotated-csrf" });
      }
      throw new Error(`Unexpected request: ${path}`);
    }));
    const auth = useAuthStore();
    auth.acceptSession(reviewerSession);

    const refresh = auth.refreshSession();
    await auth.changePassword("password", "new password");
    oldRefresh.resolve(jsonResponse(200, reviewerSession));
    await refresh;

    expect(auth.user?.username).toBe("reviewer");
    expect(auth.csrfToken).toBe("rotated-csrf");
  });

  it("does not let a pre-logout refresh rehydrate a completed logout", async () => {
    const oldRefresh = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/auth/session") return oldRefresh.promise;
      if (path === "/api/v1/auth/logout") return new Response(null, { status: 204 });
      throw new Error(`Unexpected request: ${path}`);
    }));
    const auth = useAuthStore();
    auth.acceptSession(reviewerSession);

    const refresh = auth.refreshSession();
    await auth.logout();
    oldRefresh.resolve(jsonResponse(200, reviewerSession));
    await refresh;

    expect(auth.user).toBeNull();
    expect(auth.csrfToken).toBeNull();
  });

  it.each([
    ["a 503 response", () => jsonResponse(503, {
      code: "SERVICE_UNAVAILABLE",
      message: "Temporarily unavailable",
      details: {},
      request_id: "refresh-unavailable",
    })],
    ["a network failure", () => Promise.reject(new TypeError("network unavailable"))],
  ])("keeps the current session after %s", async (_label, result) => {
    vi.stubGlobal("fetch", vi.fn(result));
    const auth = useAuthStore();
    auth.acceptSession({
      user: { username: "reviewer", display_name: "Reviewer", role: "reviewer", must_change_password: false },
      csrf_token: "reviewer-csrf",
    });

    await expect(auth.refreshSession()).rejects.toBeDefined();

    expect(auth.user?.role).toBe("reviewer");
    expect(auth.csrfToken).toBe("reviewer-csrf");
  });

  it.each([
    ["a 503 response", () => jsonResponse(503, {
      code: "SERVICE_UNAVAILABLE",
      message: "Temporarily unavailable",
      details: {},
      request_id: "logout-unavailable",
    })],
    ["a network failure", () => Promise.reject(new TypeError("network unavailable"))],
  ])("preserves the current session when logout fails with %s", async (_label, result) => {
    vi.stubGlobal("fetch", vi.fn(result));
    const auth = useAuthStore();
    auth.acceptSession(reviewerSession);

    await expect(auth.logout()).rejects.toBeDefined();

    expect(auth.user?.username).toBe("reviewer");
    expect(auth.csrfToken).toBe("reviewer-csrf");
    expect(auth.sessionNotice).toBe(zhCN.auth.logoutFailed);
  });

  it("preserves the current session when logout returns an unexpected 200 response", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(200, reviewerSession)));
    const auth = useAuthStore();
    auth.acceptSession(reviewerSession);

    await expect(auth.logout()).rejects.toBeDefined();

    expect(auth.user?.username).toBe("reviewer");
    expect(auth.csrfToken).toBe("reviewer-csrf");
    expect(auth.sessionNotice).toBe(zhCN.auth.logoutFailed);
  });

  it("rejects a second logout before it can mutate the shared browser session", async () => {
    const logoutResponse = deferred<Response>();
    const fetch = vi.fn(async () => logoutResponse.promise);
    vi.stubGlobal("fetch", fetch);
    const auth = useAuthStore();
    auth.acceptSession(reviewerSession);

    const firstLogout = auth.logout();
    const secondLogout = auth.logout();

    await expect(secondLogout).rejects.toThrow("credential mutation");
    expect(fetch).toHaveBeenCalledOnce();

    logoutResponse.resolve(new Response(null, { status: 204 }));
    await firstLogout;
    expect(auth.user).toBeNull();
    expect(auth.csrfToken).toBeNull();
  });

  it("refreshes after logout when an unrelated request triggers CSRF recovery", async () => {
    const logoutResponse = deferred<Response>();
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/auth/logout") return logoutResponse.promise;
      if (path === "/api/v2/unrelated-write") {
        return jsonResponse(403, {
          code: "CSRF_VALIDATION_FAILED",
          message: "CSRF validation failed",
          details: {},
          request_id: "unrelated-stale-csrf",
        });
      }
      if (path === "/api/v1/auth/session") return jsonResponse(200, reviewerSession);
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetch);
    const auth = useAuthStore();
    auth.acceptSession(reviewerSession);
    createAppRouter(createMemoryHistory());

    const logout = auth.logout();
    await expect(apiRequest("/api/v2/unrelated-write", z.unknown(), {
      method: "PUT",
      csrfToken: "stale",
    })).rejects.toMatchObject({ code: "CSRF_VALIDATION_FAILED" });

    logoutResponse.resolve(new Response(null, { status: 204 }));
    await logout;
    await flushPromises();

    expect(auth.user?.username).toBe("reviewer");
    expect(auth.csrfToken).toBe("reviewer-csrf");
    expect(auth.sessionNotice).toBe(zhCN.auth.sessionChanged);
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it("preserves the handler-refreshed session and notice when logout has stale CSRF", async () => {
    vi.stubGlobal("BroadcastChannel", AuthBroadcastChannel);
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/auth/logout") {
        return jsonResponse(403, {
          code: "CSRF_VALIDATION_FAILED",
          message: "CSRF validation failed",
          details: {},
          request_id: "stale-logout-csrf",
        });
      }
      if (path === "/api/v1/auth/session") return jsonResponse(200, adminSession);
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetch);
    const auth = useAuthStore();
    auth.acceptSession(reviewerSession);
    createAppRouter(createMemoryHistory());

    await expect(auth.logout()).rejects.toMatchObject({
      code: "CSRF_VALIDATION_FAILED",
      requestId: "stale-logout-csrf",
    });

    expect(fetch).toHaveBeenCalledTimes(2);
    expect(auth.user?.username).toBe("admin");
    expect(auth.csrfToken).toBe("admin-csrf");
    expect(auth.sessionNotice).toBe(zhCN.auth.sessionChanged);
    expect(AuthBroadcastChannel.sent).toEqual([]);
  });

  it("shows a logout failure when stale-CSRF recovery is temporarily unavailable", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/auth/logout") {
        return jsonResponse(403, {
          code: "CSRF_VALIDATION_FAILED",
          message: "CSRF validation failed",
          details: {},
          request_id: "stale-logout-csrf",
        });
      }
      if (path === "/api/v1/auth/session") {
        return jsonResponse(503, {
          code: "SERVICE_UNAVAILABLE",
          message: "Temporarily unavailable",
          details: {},
          request_id: "csrf-refresh-unavailable",
        });
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetch);
    const auth = useAuthStore();
    auth.acceptSession(reviewerSession);
    createAppRouter(createMemoryHistory());

    await expect(auth.logout()).rejects.toMatchObject({
      code: "CSRF_VALIDATION_FAILED",
      requestId: "stale-logout-csrf",
    });

    expect(fetch).toHaveBeenCalledTimes(2);
    expect(auth.user?.username).toBe("reviewer");
    expect(auth.csrfToken).toBe("reviewer-csrf");
    expect(auth.sessionNotice).toBe(zhCN.auth.logoutFailed);
  });

  it("keeps a pending session-change notice across a transient refresh failure", async () => {
    let reads = 0;
    vi.stubGlobal("fetch", vi.fn(async () => {
      reads += 1;
      if (reads === 1) {
        return jsonResponse(503, {
          code: "SERVICE_UNAVAILABLE",
          message: "Temporarily unavailable",
          details: {},
          request_id: "refresh-unavailable",
        });
      }
      return jsonResponse(200, adminSession);
    }));
    const auth = useAuthStore();
    auth.acceptSession(reviewerSession);

    await expect(auth.refreshSession({ sessionChanged: true })).rejects.toBeDefined();
    await auth.refreshSession();

    expect(auth.user?.username).toBe("admin");
    expect(auth.csrfToken).toBe("admin-csrf");
    expect(auth.sessionNotice).toBe(zhCN.auth.sessionChanged);
  });

  it("clears an existing session after an authoritative 401 refresh", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(401, {
      code: "AUTHENTICATION_REQUIRED",
      message: "Authentication required",
      details: {},
      request_id: "refresh-expired",
    })));
    const auth = useAuthStore();
    auth.acceptSession({
      user: { username: "reviewer", display_name: "Reviewer", role: "reviewer", must_change_password: false },
      csrf_token: "reviewer-csrf",
    });

    await auth.refreshSession();

    expect(auth.user).toBeNull();
    expect(auth.csrfToken).toBeNull();
  });

  it("does not carry an old session notice through sign-out into the next login", async () => {
    let sessionReads = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/auth/login") return jsonResponse(200, reviewerSession);
      if (path !== "/api/v1/auth/session") throw new Error(`Unexpected request: ${path}`);
      sessionReads += 1;
      if (sessionReads === 1) return jsonResponse(200, adminSession);
      return jsonResponse(401, {
        code: "AUTHENTICATION_REQUIRED",
        message: "Authentication required",
        details: {},
        request_id: "refresh-expired",
      });
    }));
    const auth = useAuthStore();
    auth.acceptSession(reviewerSession);

    await auth.refreshSession({ sessionChanged: true });
    expect(auth.sessionNotice).toBe(zhCN.auth.sessionChanged);

    await auth.refreshSession();
    expect(auth.user).toBeNull();
    expect(auth.sessionNotice).toBeNull();

    await expect(auth.login("reviewer", "password")).resolves.toBe(true);
    expect(auth.sessionNotice).toBeNull();
  });

  it("routes away from a protected page when refreshed authorization no longer permits it", async () => {
    const auth = useAuthStore();
    auth.acceptSession({
      user: { username: "admin", display_name: "Admin", role: "admin", must_change_password: false },
      csrf_token: "admin-csrf",
    });
    const router = createAppRouter(createMemoryHistory());
    await router.push("/admin/users");
    await router.isReady();
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(200, {
      user: { username: "reviewer", display_name: "Reviewer", role: "reviewer", must_change_password: false },
      csrf_token: "reviewer-csrf",
    })));

    await auth.refreshSession({ sessionChanged: true });
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/papers");
  });

  it("leaves login for a safe redirect after another tab authenticates", async () => {
    const auth = useAuthStore();
    auth.clearSession();
    const router = createAppRouter(createMemoryHistory());
    await router.push({
      path: "/login",
      query: { redirect: "/papers?page=2&target=kinase" },
    });
    await router.isReady();
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(200, reviewerSession)));

    await auth.refreshSession({ sessionChanged: true });
    await flushPromises();

    expect(router.currentRoute.value.fullPath).toBe("/papers?page=2&target=kinase");
  });

  it.each([
    "/review/papers/60000000-0000-4000-8000-000000000001?workspace=60000000-0000-4000-8000-000000000002",
    "/change-password",
  ])("leaves identity-bound route %s after a same-role username replacement", async (path) => {
    const auth = useAuthStore();
    auth.acceptSession({
      user: { ...reviewerSession.user, username: "reviewer.a" },
      csrf_token: "reviewer-a-csrf",
    });
    const router = createAppRouter(createMemoryHistory());
    await router.push(path);
    await router.isReady();
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(200, {
      user: { ...reviewerSession.user, username: "reviewer.b" },
      csrf_token: "reviewer-b-csrf",
    })));

    await auth.refreshSession({ sessionChanged: true });
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/papers");
    expect(auth.sessionNotice).toBe(zhCN.auth.sessionChanged);
  });

  it("routes an authoritative 401 refresh from a protected page to login", async () => {
    const auth = useAuthStore();
    auth.acceptSession({
      user: { username: "reviewer", display_name: "Reviewer", role: "reviewer", must_change_password: false },
      csrf_token: "reviewer-csrf",
    });
    const router = createAppRouter(createMemoryHistory());
    await router.push("/papers");
    await router.isReady();
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(401, {
      code: "AUTHENTICATION_REQUIRED",
      message: "Authentication required",
      details: {},
      request_id: "refresh-expired",
    })));

    await auth.refreshSession({ sessionChanged: true });
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/login");
    expect(router.currentRoute.value.query.redirect).toBe("/papers");
  });

  it("renders and dismisses the persistent session-change warning", async () => {
    const auth = useAuthStore();
    auth.acceptSession({
      user: { username: "reviewer", display_name: "Reviewer", role: "reviewer", must_change_password: false },
      csrf_token: "reviewer-csrf",
    });
    const router = createAppRouter(createMemoryHistory());
    await router.push("/papers");
    await router.isReady();
    const wrapper = mount(AppShell, {
      global: { plugins: [router], stubs: { RouterView: true } },
    });
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(200, {
      user: { username: "admin", display_name: "Admin", role: "admin", must_change_password: false },
      csrf_token: "admin-csrf",
    })));

    await auth.refreshSession({ sessionChanged: true });
    await flushPromises();

    expect(wrapper.get("[data-session-notice]").text()).toContain(zhCN.auth.sessionChanged);
    await wrapper.get("[data-dismiss-session-notice]").trigger("click");
    expect(wrapper.find("[data-session-notice]").exists()).toBe(false);
  });

  it("keeps the shell open and shows a warning when sign out fails", async () => {
    const auth = useAuthStore();
    auth.acceptSession(reviewerSession);
    const router = createAppRouter(createMemoryHistory());
    await router.push("/papers");
    await router.isReady();
    const wrapper = mount(AppShell, {
      global: { plugins: [router], stubs: { RouterView: true } },
    });
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(503, {
      code: "SERVICE_UNAVAILABLE",
      message: "Temporarily unavailable",
      details: {},
      request_id: "logout-unavailable",
    })));

    await wrapper.get(".sign-out").trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/papers");
    expect(auth.user?.username).toBe("reviewer");
    expect(wrapper.get("[data-session-notice]").text()).toContain(zhCN.auth.logoutFailed);
  });

  it("disposes router-owned session synchronization, watchers, and API handlers on app unmount", async () => {
    vi.stubGlobal("BroadcastChannel", AuthBroadcastChannel);
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.acceptSession(adminSession);
    const router = createAppRouter(createMemoryHistory());
    const app = createApp({ render: () => h("div") });
    app.use(pinia);
    app.use(router);
    app.mount(document.createElement("div"));
    await router.push("/admin/users");
    await router.isReady();

    app.unmount();
    await router.push("/admin/users");
    auth.acceptSession(reviewerSession);
    await flushPromises();
    expect(AuthBroadcastChannel.instances[0]?.closed).toBe(true);
    expect(router.currentRoute.value.path).toBe("/admin/users");

    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v2/test") {
        return jsonResponse(403, {
          code: "CSRF_VALIDATION_FAILED",
          message: "CSRF validation failed",
          details: {},
          request_id: "disposed-router",
        });
      }
      return jsonResponse(200, adminSession);
    });
    vi.stubGlobal("fetch", fetch);

    await expect(apiRequest("/api/v2/test", z.unknown())).rejects.toMatchObject({
      code: "CSRF_VALIDATION_FAILED",
    });
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("keeps focus synchronization when localStorage access is denied", async () => {
    vi.stubGlobal("BroadcastChannel", undefined);
    vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
      throw new DOMException("Storage denied", "SecurityError");
    });
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(200, adminSession)));
    const auth = useAuthStore();
    auth.acceptSession(reviewerSession);

    expect(() => auth.startSessionSync()).not.toThrow();
    window.dispatchEvent(new Event("focus"));
    await flushPromises();

    expect(auth.user?.username).toBe("admin");
  });
});

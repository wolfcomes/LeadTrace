import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";

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

  postMessage(message: unknown): void {
    AuthBroadcastChannel.sent.push(message);
  }

  close(): void {}
}


describe("authenticated login flow", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    AuthBroadcastChannel.sent.length = 0;
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
});

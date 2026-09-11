import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";

import LoginPage from "../src/auth/LoginPage.vue";
import { useAuthStore } from "../src/auth/store";
import { createAppRouter } from "../src/app/router";


function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      "X-Request-ID": "frontend-auth-request",
    },
  });
}


describe("authenticated login flow", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
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

  it("routes first-login accounts to mandatory password change", async () => {
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

    expect(router.currentRoute.value.path).toBe("/change-password");
    expect(useAuthStore().user?.role).toBe("reviewer");
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
});

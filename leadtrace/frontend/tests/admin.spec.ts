import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";

import App from "../src/App.vue";
import { createAppRouter } from "../src/app/router";
import { useAuthStore } from "../src/auth/store";

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "X-Request-ID": "admin-ui" },
  });
}

describe("Admin console", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    useAuthStore().acceptSession({
      user: { username: "admin", display_name: "管理员", role: "admin", must_change_password: false },
      csrf_token: "csrf",
    });
  });

  afterEach(() => vi.unstubAllGlobals());

  it("renders the user lifecycle page from the admin route", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response([])));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/admin/users");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();
    expect(wrapper.get("h1").text()).toBe("用户管理");
    expect(wrapper.get("[data-admin-users]")).toBeTruthy();
  });

  it("shows actionable job retry controls and system health summaries", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/admin/jobs") return response([{ id: "job-1", status: "failed", error_message: "render failed" }]);
      if (path === "/api/v1/admin/system") return response({ status: "degraded", request_id: "req-1", checks: { database: { status: "ok", summary: "healthy" } } });
      return response([]);
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/admin/jobs");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();
    expect(wrapper.get("h1").text()).toBe("任务队列");
    expect(wrapper.get("[data-job-id='job-1']").text()).toContain("render failed");
    await router.push("/admin/system");
    await flushPromises();
    expect(wrapper.get("h1").text()).toBe("系统状态");
    expect(wrapper.text()).toContain("healthy");
  });
});

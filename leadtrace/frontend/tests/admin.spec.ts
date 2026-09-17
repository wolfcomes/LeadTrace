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
    vi.stubGlobal("fetch", vi.fn(async () => response([{
      id: "91000000-0000-4000-8000-000000000010",
      username: "reviewer.one",
      display_name: "核查员一",
      role: "reviewer",
      is_enabled: true,
      must_change_password: false,
    }])));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/admin/users");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();
    expect(wrapper.get("h1").text()).toBe("用户管理");
    expect(wrapper.get("[data-admin-users]")).toBeTruthy();
    expect(wrapper.get("[data-admin-users] table").classes()).toContain("data-table");
    expect(wrapper.get("[data-admin-users] tbody .actions").classes()).toContain("table-actions");
    await wrapper.get("[data-admin-users] header button").trigger("click");
    expect(wrapper.get("[data-admin-users] .create-form").classes()).toContain("workspace-toolbar");
    expect(wrapper.find("input[type='password']").exists()).toBe(false);
    expect(wrapper.get("select[name='role']")).toBeTruthy();
  });

  it("confirms and resets a managed account to the server default", async () => {
    const targetId = "91000000-0000-4000-8000-000000000001";
    const calls: Array<{ path: string; init?: RequestInit }> = [];
    const target = {
      id: targetId,
      username: "reviewer.one",
      display_name: "核查员一",
      role: "reviewer",
      is_enabled: true,
      must_change_password: false,
    };
    vi.stubGlobal("confirm", vi.fn(() => true));
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      calls.push({ path, init });
      return response(init?.method === "PATCH" ? target : [target]);
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/admin/users");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    await wrapper.get("[data-reset-default]").trigger("click");
    await flushPromises();

    expect(confirm).toHaveBeenCalledOnce();
    expect(calls.at(-1)?.path).toBe(`/api/v1/users/${targetId}/password`);
    expect(calls.at(-1)?.init?.method).toBe("PATCH");
    expect(calls.at(-1)?.init?.body).toBeUndefined();
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
    expect(wrapper.get(".admin-panel").classes()).toContain("table-wrap");
    expect(wrapper.get(".admin-panel table").classes()).toContain("data-table");
    expect(wrapper.get("[data-job-id='job-1'] td:nth-child(2) span").classes()).toContain("status-chip");
    expect(wrapper.get("[data-job-id='job-1']").text()).toContain("render failed");
    expect(wrapper.get("[data-navigation]").text()).toContain("任务队列");
    await router.push("/admin/system");
    await flushPromises();
    expect(wrapper.get("h1").text()).toBe("系统状态");
    expect(wrapper.get("[data-check='database']").classes()).toContain("panel");
    expect(wrapper.get("[data-check='database'] .check-status").classes()).toContain("status-chip");
    expect(wrapper.text()).toContain("healthy");
  });

});

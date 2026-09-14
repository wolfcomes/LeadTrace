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
    await router.push("/admin/system");
    await flushPromises();
    expect(wrapper.get("h1").text()).toBe("系统状态");
    expect(wrapper.get("[data-check='database']").classes()).toContain("panel");
    expect(wrapper.get("[data-check='database'] .check-status").classes()).toContain("status-chip");
    expect(wrapper.text()).toContain("healthy");
  });

  it("reviews import candidates with Chinese states and protected decisions", async () => {
    const pendingId = "81000000-0000-4000-8000-000000000001";
    const approvedId = "81000000-0000-4000-8000-000000000002";
    const candidate = (id: string, status: string, decision: unknown = null) => ({
      id,
      import_batch_id: "82000000-0000-4000-8000-000000000001",
      status,
      is_current: status === "published",
      manifest: {
        schema_version: 1,
        source_fingerprint: "a".repeat(64),
        status: "imported_baseline",
        is_current: false,
        counts: { corpus_papers: 672, compound_entities: 4301 },
        integrity: { dangling_entity_references: 0 },
        asset_linkage: {
          resolved_references: 5033,
          unique_resolved_assets: 4890,
          missing_references: 14,
          ambiguous_references: 3,
          corrupt_references: 2,
        },
        revision_count: 10000,
      },
      decision,
      created_at: "2026-09-13T00:00:00Z",
    });
    const candidates = [
      candidate(pendingId, "imported_baseline"),
      candidate(approvedId, "approved", {
        id: "83000000-0000-4000-8000-000000000002",
        decision: "approve",
        actor_id: "10000000-0000-4000-8000-000000000001",
        reason: "已核对导入清单",
        manifest_hash: "b".repeat(64),
        created_at: "2026-09-13T01:00:00Z",
      }),
      candidate("81000000-0000-4000-8000-000000000003", "rejected", {
        id: "83000000-0000-4000-8000-000000000003",
        decision: "reject",
        actor_id: "10000000-0000-4000-8000-000000000001",
        reason: "数据需重新导入",
        manifest_hash: "c".repeat(64),
        created_at: "2026-09-13T01:00:00Z",
      }),
      candidate("81000000-0000-4000-8000-000000000004", "published", {
        id: "83000000-0000-4000-8000-000000000004",
        decision: "approve",
        actor_id: "10000000-0000-4000-8000-000000000001",
        reason: "已发布",
        manifest_hash: "d".repeat(64),
        created_at: "2026-09-13T01:00:00Z",
      }),
    ];
    const calls: Array<{ path: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      calls.push({ path, init });
      if (path === "/api/v1/admin/imports") return response([]);
      if (path === "/api/v1/admin/import-candidates") return response(candidates);
      if (path === `/api/v1/admin/import-candidates/${pendingId}/decision`) {
        return response({
          ...candidate(pendingId, "approved"),
          decision: {
            id: "83000000-0000-4000-8000-000000000001",
            decision: "approve",
            actor_id: "10000000-0000-4000-8000-000000000001",
            reason: "核对导入计数与完整性",
            manifest_hash: "e".repeat(64),
            created_at: "2026-09-13T02:00:00Z",
          },
          idempotent: false,
          request_id: "candidate-decision",
        });
      }
      return response({});
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/admin/imports");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.get(".import-controls").classes()).toContain("workspace-toolbar");
    expect(wrapper.get(".candidate-panel table").classes()).toContain("data-table");
    expect(wrapper.get(".candidate-state").classes()).toContain("status-chip");
    expect(wrapper.text()).toContain("待审批");
    expect(wrapper.text()).toContain("已批准，待发布");
    expect(wrapper.text()).toContain("已拒绝");
    expect(wrapper.text()).toContain("已发布");
    expect(wrapper.text()).toContain("5,033 解析引用");
    expect(wrapper.text()).toContain("4,890 唯一资产");
    expect(wrapper.text()).toContain("14 缺失");
    expect(wrapper.text()).toContain("3 歧义");
    expect(wrapper.text()).toContain("2 损坏");
    expect(wrapper.findAll("[data-candidate-decision]")).toHaveLength(2);
    const approve = wrapper.get(`[data-candidate-approve='${pendingId}']`);
    expect(approve.attributes("disabled")).toBeDefined();
    await wrapper.get(`[data-candidate-reason='${pendingId}']`).setValue("核对导入计数与完整性");
    expect(approve.attributes("disabled")).toBeUndefined();
    await approve.trigger("click");
    await flushPromises();

    const decisionRequest = calls.find(
      (call) => call.path === `/api/v1/admin/import-candidates/${pendingId}/decision`,
    );
    expect(decisionRequest).toBeTruthy();
    expect(new Headers(decisionRequest?.init?.headers).get("X-CSRF-Token")).toBe("csrf");
    expect(JSON.parse(String(decisionRequest?.init?.body))).toEqual({
      action: "approve",
      reason: "核对导入计数与完整性",
    });
    const publishLink = wrapper.get(`[data-candidate-publish='${approvedId}']`);
    expect(publishLink.attributes("href")).toBe(`/admin/releases?candidate=${approvedId}`);
  });
});

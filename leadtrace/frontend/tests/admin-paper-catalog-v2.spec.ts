import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";

import App from "../src/App.vue";
import { createAppRouter } from "../src/app/router";
import { useAuthStore } from "../src/auth/store";


const paperId = "20000000-0000-4000-8000-000000000001";
const errorPaperId = "20000000-0000-4000-8000-000000000002";
const reviewerId = "10000000-0000-4000-8000-000000000002";
const workspaceId = "30000000-0000-4000-8000-000000000001";
const taskId = "40000000-0000-4000-8000-000000000001";

const sections = [
  "bibliography",
  "compounds",
  "structures",
  "lineages",
  "edge_evidence",
  "activities",
].map((section_key) => ({ section_key, state: "pending", note: null }));

function catalogPaper(overrides: Record<string, unknown> = {}) {
  return {
    id: paperId,
    paper_key: "LT-JMC-2024-67-05-001",
    title: "Selective kinase lead optimization",
    journal: "Journal of Medicinal Chemistry",
    publication_year: 2024,
    volume: "67",
    issue: "5",
    doi: "10.1021/acs.jmedchem.4c0001",
    catalog_state: "verified",
    source: {
      id: "50000000-0000-4000-8000-000000000001",
      asset_id: "60000000-0000-4000-8000-000000000001",
      source_root_key: "source_pdfs",
      source_key: "volume67 issue5/paper-01.pdf",
      sha256: "a".repeat(64),
      byte_size: 123456,
      page_count: 14,
      integrity_state: "verified",
    },
    review: {
      review_task_id: taskId,
      workspace_id: workspaceId,
      assigned_reviewer_id: reviewerId,
      assignee_display_name: "核查员一",
      task_status: "changes_requested",
      workspace_state: "editing",
      sections_resolved: 4,
      sections_total: 6,
      submission_state: "changes_requested",
    },
    ...overrides,
  };
}

const pagePayload = {
  items: [
    catalogPaper(),
    catalogPaper({
      id: errorPaperId,
      paper_key: "LT-JMC-2024-67-05-002",
      title: "Source integrity failure",
      doi: null,
      catalog_state: "source_error",
      source: {
        ...catalogPaper().source,
        id: "50000000-0000-4000-8000-000000000002",
        asset_id: "60000000-0000-4000-8000-000000000002",
        source_key: "volume67 issue5/paper-02.pdf",
        sha256: "b".repeat(64),
        integrity_state: "missing",
      },
      review: null,
    }),
  ],
  total: 42,
  limit: 20,
  offset: 20,
};

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "X-Request-ID": "catalog-v2-ui" },
  });
}

function adminSession(): void {
  setActivePinia(createPinia());
  useAuthStore().acceptSession({
    user: {
      username: "admin",
      display_name: "管理员",
      role: "admin",
      must_change_password: false,
    },
    csrf_token: "csrf-v2",
  });
}

describe("paper-centric Admin catalog", () => {
  beforeEach(adminSession);
  afterEach(() => vi.unstubAllGlobals());

  it("renders the exact catalog, Source, Reviewer, progress, and submission columns", async () => {
    const requested: URL[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://leadtrace.test");
      requested.push(url);
      return response(pagePayload);
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/admin/papers?page=2&search=kinase");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    expect(requested[0]?.pathname).toBe("/api/v2/admin/papers");
    expect(requested[0]?.searchParams.get("limit")).toBe("20");
    expect(requested[0]?.searchParams.get("offset")).toBe("20");
    expect(requested[0]?.searchParams.get("search")).toBe("kinase");
    expect(wrapper.get("h1").text()).toBe("文章目录");
    expect(wrapper.get("[data-paper-catalog]").text()).toContain("Journal of Medicinal Chemistry");
    expect(wrapper.get("[data-paper-catalog]").text()).toContain("Volume 67 · Issue 5");
    expect(wrapper.get("[data-paper-catalog]").text()).toContain("核查员一");
    expect(wrapper.get("[data-paper-catalog]").text()).toContain("4 / 6");
    expect(wrapper.get("[data-paper-catalog]").text()).toContain("已退回修改");
    expect(wrapper.get("[data-paper-catalog]").text()).toContain("PDF 缺失");
    expect(wrapper.find("[data-ai-action]").exists()).toBe(false);
    expect(wrapper.get(`[data-paper-id='${errorPaperId}'] [data-assign]`).attributes("disabled")).toBeDefined();
  });

  it("keeps search and page in the URL while paging and opening details", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response(pagePayload)));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/admin/papers?page=2&search=kinase");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    await wrapper.get("[data-next-page]").trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.query).toMatchObject({ page: "3", search: "kinase" });

    await wrapper.get(`[data-paper-id='${paperId}'] [data-paper-detail]`).trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.path).toBe(`/admin/papers/${paperId}`);
    expect(router.currentRoute.value.query).toMatchObject({ page: "3", search: "kinase" });
  });

  it("assigns a healthy unassigned Paper to an enabled Reviewer with CSRF", async () => {
    const unassignedPage = { ...pagePayload, items: [catalogPaper({ review: null })], total: 1, offset: 0 };
    const calls: Array<{ url: URL; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://leadtrace.test");
      calls.push({ url, init });
      if (url.pathname === "/api/v1/users") {
        return response([
          { id: reviewerId, username: "reviewer.one", display_name: "核查员一", role: "reviewer", is_enabled: true, must_change_password: false },
          { id: "10000000-0000-4000-8000-000000000003", username: "disabled", display_name: "停用账号", role: "reviewer", is_enabled: false, must_change_password: false },
        ]);
      }
      if (url.pathname.endsWith("/assign")) {
        return response({
          review_task_id: taskId,
          workspace_id: workspaceId,
          paper_id: paperId,
          assigned_reviewer_id: reviewerId,
          task_status: "assigned",
          task_version: 1,
          workspace_state: "editing",
          workspace_version: 1,
          sections,
        }, 201);
      }
      return response(unassignedPage);
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/admin/papers");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    await wrapper.get("[data-assign]").trigger("click");
    await flushPromises();
    expect(wrapper.get("[role='dialog']").text()).toContain("分配 Reviewer");
    expect(wrapper.findAll("[data-reviewer-option]")).toHaveLength(1);
    await wrapper.get("[data-assignment-form]").trigger("submit");
    await flushPromises();

    const assignment = calls.find((call) => call.url.pathname.endsWith("/assign"));
    expect(assignment?.init?.method).toBe("POST");
    expect(new Headers(assignment?.init?.headers).get("X-CSRF-Token")).toBe("csrf-v2");
    expect(JSON.parse(String(assignment?.init?.body))).toEqual({ reviewer_id: reviewerId });
    expect(wrapper.find("[role='dialog']").exists()).toBe(false);
    expect(wrapper.get(`[data-paper-id='${paperId}']`).text()).toContain("核查员一");
    expect(wrapper.get(`[data-paper-id='${paperId}']`).text()).toContain("0 / 6");
  });

  it("keeps the assignment dialog open and explains duplicate assignment conflicts", async () => {
    const unassignedPage = { ...pagePayload, items: [catalogPaper({ review: null })], total: 1, offset: 0 };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://leadtrace.test");
      if (url.pathname === "/api/v1/users") {
        return response([{ id: reviewerId, username: "reviewer.one", display_name: "核查员一", role: "reviewer", is_enabled: true, must_change_password: false }]);
      }
      if (url.pathname.endsWith("/assign")) {
        return response({ code: "ACTIVE_ASSIGNMENT_EXISTS", message: "Paper already assigned", request_id: "duplicate-request", details: {} }, 409);
      }
      return response(unassignedPage);
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/admin/papers");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    await wrapper.get("[data-assign]").trigger("click");
    await flushPromises();
    await wrapper.get("[data-assignment-form]").trigger("submit");
    await flushPromises();

    expect(wrapper.get("[role='dialog'] [role='alert']").text()).toContain("已有活动分配");
    expect(wrapper.get("[role='dialog'] [role='alert']").text()).toContain("duplicate-request");
  });

  it("keeps keyboard focus inside the assignment dialog and restores it on Escape", async () => {
    const unassignedPage = { ...pagePayload, items: [catalogPaper({ review: null })], total: 1, offset: 0 };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://leadtrace.test");
      if (url.pathname === "/api/v1/users") {
        return response([{ id: reviewerId, username: "reviewer.one", display_name: "核查员一", role: "reviewer", is_enabled: true, must_change_password: false }]);
      }
      return response(unassignedPage);
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/admin/papers");
    await router.isReady();
    const wrapper = mount(App, { attachTo: document.body, global: { plugins: [router] } });
    await flushPromises();

    const trigger = wrapper.get("[data-assign]");
    (trigger.element as HTMLElement).focus();
    await trigger.trigger("click");
    await flushPromises();

    const dialog = wrapper.get("[role='dialog']");
    expect(document.activeElement).toBe(dialog.get("select").element);
    const confirm = dialog.get("button[type='submit']");
    (confirm.element as HTMLElement).focus();
    await dialog.trigger("keydown", { key: "Tab" });
    expect(document.activeElement).toBe(dialog.get("button[aria-label='关闭']").element);

    await dialog.trigger("keydown", { key: "Escape" });
    await flushPromises();
    expect(wrapper.find("[role='dialog']").exists()).toBe(false);
    expect(document.activeElement).toBe(trigger.element);
    wrapper.unmount();
  });
});

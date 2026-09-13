import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";

import App from "../src/App.vue";
import { createAppRouter } from "../src/app/router";
import { useAuthStore } from "../src/auth/store";


const paperId = "20000000-0000-4000-8000-000000000001";
const reviewerId = "10000000-0000-4000-8000-000000000002";
const taskId = "30000000-0000-4000-8000-000000000001";

const source = {
  kind: "candidate",
  candidate_id: "80000000-0000-4000-8000-000000000001",
  release_id: null,
  title: "AI 提取基线候选",
  status: "imported_baseline",
  dataset_class: "ai_extracted_baseline",
  verification_status: "unverified",
  publication_status: "unpublished",
};

const quality = {
  compounds: 12,
  structures: 11,
  confirmed_structures: 9,
  evidence: 4,
  activities: 7,
  lineages: 2,
  lineage_edges: 8,
  unresolved_relations: 1,
  visual_objects: 5,
};

function paper(workflowState: string, index: number) {
  return {
    id: index === 1 ? paperId : `20000000-0000-4000-8000-00000000000${index}`,
    revision_id: null,
    paper_key: `paper-${index}`,
    doi: `10.1000/${index}`,
    title: `Lead optimization article ${index}`,
    year: "2025",
    target: "Kinase A",
    review_status: "unreviewed",
    workflow_state: workflowState,
    publication_status: index === 1 ? "published" : "unpublished",
    verification_status: "unverified",
    quality,
    task: null,
    changeset: null,
    can_modify: false,
    modification_blocker: index === 1 ? "review_task_required" : "baseline_must_be_published",
  };
}

const listPayload = {
  request_id: "admin-paper-catalog",
  source,
  status_counts: {
    initial: 1,
    ai_baseline_unassigned: 668,
    ai_baseline_in_review: 1,
    human_review_pending_approval: 1,
    admin_approved: 1,
  },
  pagination: { page: 1, page_size: 20, total_items: 672, total_pages: 34 },
  filters: {},
  items: [
    paper("initial", 1),
    paper("ai_baseline_unassigned", 2),
    paper("ai_baseline_in_review", 3),
    paper("human_review_pending_approval", 4),
    paper("admin_approved", 5),
  ],
};

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "X-Request-ID": "admin-paper-ui" },
  });
}

describe("Admin Paper catalog", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    useAuthStore().acceptSession({
      user: { username: "admin", display_name: "管理员", role: "admin", must_change_password: false },
      csrf_token: "csrf",
    });
  });

  afterEach(() => vi.unstubAllGlobals());

  it("shows the 672 database Papers, five states, and independent quality badges", async () => {
    const requests: URL[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://leadtrace.test");
      requests.push(url);
      return response(listPayload);
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/admin/papers");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.get("h1").text()).toBe("文章目录");
    expect(wrapper.text()).toContain("共 672 篇");
    expect(wrapper.text()).toContain("初始状态");
    expect(wrapper.text()).toContain("AI 提取基线（未分配）");
    expect(wrapper.text()).toContain("AI 提取基线（已分配，人工核验进行中）");
    expect(wrapper.text()).toContain("人工核验结束（待批）");
    expect(wrapper.text()).toContain("Admin 已批准");
    expect(wrapper.text()).toContain("未验证");
    expect(wrapper.text()).toContain("未发布");
    expect(wrapper.findAll("[data-admin-paper]")).toHaveLength(5);

    await wrapper.get("#admin-paper-workflow").setValue("ai_baseline_unassigned");
    await wrapper.get("[data-admin-paper-filters]").trigger("submit");
    await flushPromises();

    expect(router.currentRoute.value.query.workflow_state).toBe("ai_baseline_unassigned");
    expect(requests.at(-1)?.searchParams.get("workflow_state")).toBe("ai_baseline_unassigned");
  });

  it("shows database detail, source PDF, assignment, and a traceable edit entry", async () => {
    const calls: Array<{ url: URL; init?: RequestInit }> = [];
    const detailPaper = {
      ...paper("ai_baseline_unassigned", 1),
      publication_status: "published",
      modification_blocker: "review_task_required",
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://leadtrace.test");
      calls.push({ url, init });
      if (url.pathname === `/api/v1/admin/papers/${paperId}`) {
        return response({
          request_id: "admin-paper-detail",
          source: { ...source, kind: "release", release_id: "90000000-0000-4000-8000-000000000001", publication_status: "published" },
          paper: detailPaper,
          source_pdf_url: `/api/v1/papers/${paperId}/source-pdf?kind=article&release_id=90000000-0000-4000-8000-000000000001`,
          review_entry: null,
        });
      }
      if (url.pathname === "/api/v1/users") {
        return response([{
          id: reviewerId,
          username: "reviewer.one",
          display_name: "核查员一",
          role: "reviewer",
          is_enabled: true,
          must_change_password: false,
        }]);
      }
      if (url.pathname === "/api/v1/review/tasks" && init?.method === "POST") {
        return response({
          id: taskId,
          paper_id: paperId,
          assigned_reviewer_id: reviewerId,
          created_by_id: "10000000-0000-4000-8000-000000000001",
          status: "open",
          priority: 50,
          version: 1,
          created_at: "2026-09-13T08:00:00Z",
          updated_at: "2026-09-13T08:00:00Z",
        }, 201);
      }
      return response({});
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/admin/papers/${paperId}`);
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.text()).toContain("Lead optimization article 1");
    expect(wrapper.text()).toContain("10.1000/1");
    expect(wrapper.text()).toContain("AI 提取基线（未分配）");
    expect(wrapper.text()).not.toContain("ai_baseline_unassigned");
    expect(wrapper.get("[data-quality-compounds]").text()).toContain("12");
    expect(wrapper.get("[data-source-pdf]").attributes("href")).toBe(
      `/api/v1/papers/${paperId}/source-pdf?kind=article&release_id=90000000-0000-4000-8000-000000000001`,
    );
    await wrapper.get("#paper-reviewer").setValue(reviewerId);
    await wrapper.get("[data-assignment-form]").trigger("submit");
    await flushPromises();

    const assignment = calls.find((call) => (
      call.url.pathname === "/api/v1/review/tasks" && call.init?.method === "POST"
    ));
    expect(new Headers(assignment?.init?.headers).get("X-CSRF-Token")).toBe("csrf");
    expect(JSON.parse(String(assignment?.init?.body))).toEqual({
      paper_id: paperId,
      assigned_reviewer_id: reviewerId,
      priority: 50,
    });
    expect(wrapper.get("[data-open-review]").attributes("href")).toBe(
      `/review/changesets?task=${taskId}`,
    );
  });

  it("keeps the catalog route Admin-only", async () => {
    useAuthStore().acceptSession({
      user: { username: "visitor", display_name: "访客", role: "visitor", must_change_password: false },
      csrf_token: "csrf",
    });
    vi.stubGlobal("fetch", vi.fn(async () => response(listPayload)));
    const router = createAppRouter(createMemoryHistory());

    await router.push("/admin/papers");
    await router.isReady();

    expect(router.currentRoute.value.path).toBe("/overview");
  });
});

import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";

import App from "../src/App.vue";
import { ApiError } from "../src/api/client";
import { createAppRouter } from "../src/app/router";
import { useAuthStore } from "../src/auth/store";
import { createAutosave } from "../src/review/autosave";


const paperId = "20000000-0000-4000-8000-000000000001";
const reviewerId = "30000000-0000-4000-8000-000000000001";
const releaseId = "40000000-0000-4000-8000-000000000001";
const openTaskId = "50000000-0000-4000-8000-000000000001";
const activeTaskId = "50000000-0000-4000-8000-000000000002";
const changesetId = "60000000-0000-4000-8000-000000000001";
const itemId = "70000000-0000-4000-8000-000000000001";
const baseRevisionId = "80000000-0000-4000-8000-000000000001";
const proposedRevisionId = "80000000-0000-4000-8000-000000000002";
const reviewerAutosaveKey = `leadtrace:review:autosave:reviewer.one:${changesetId}`;

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "X-Request-ID": "review-ui-request" },
  });
}

const tasks = [
  {
    id: openTaskId,
    paper_id: paperId,
    assigned_reviewer_id: reviewerId,
    created_by_id: reviewerId,
    status: "open",
    priority: 90,
    version: 1,
    created_at: "2026-09-12T01:00:00Z",
    updated_at: "2026-09-12T01:00:00Z",
  },
  {
    id: activeTaskId,
    paper_id: "20000000-0000-4000-8000-000000000002",
    assigned_reviewer_id: reviewerId,
    created_by_id: reviewerId,
    status: "in_progress",
    priority: 40,
    version: 2,
    created_at: "2026-09-11T01:00:00Z",
    updated_at: "2026-09-12T02:00:00Z",
  },
];

const draft = {
  id: changesetId,
  review_task_id: activeTaskId,
  paper_id: tasks[1].paper_id,
  owner_id: reviewerId,
  base_release_id: releaseId,
  title: "核查 paper-25 的文献元数据",
  reason: "人工核查标题与证据文本",
  workflow_state: "draft",
  version: 3,
  validation_results: {},
  submitted_snapshot: null,
  submitted_content_hash: null,
  submitted_at: null,
  created_at: "2026-09-12T01:30:00Z",
  updated_at: "2026-09-12T02:00:00Z",
};

const item = {
  id: itemId,
  changeset_id: changesetId,
  paper_id: tasks[1].paper_id,
  object_id: paperId,
  object_kind: "paper",
  base_revision_id: baseRevisionId,
  proposed_revision_id: proposedRevisionId,
  proposed_snapshot: {
    normalized_values: {
      title_guess: "修订后的标题",
      year: "2026",
      target: "Kinase A",
      review_status: "unreviewed",
    },
  },
  content_hash: "a".repeat(64),
  sequence: 1,
  changeset_version: 3,
  created_at: "2026-09-12T01:40:00Z",
};

const evidenceItem = {
  ...item,
  id: "70000000-0000-4000-8000-000000000002",
  object_id: "71000000-0000-4000-8000-000000000001",
  object_kind: "evidence",
  base_revision_id: "81000000-0000-4000-8000-000000000001",
  proposed_revision_id: "81000000-0000-4000-8000-000000000002",
  proposed_snapshot: {
    normalized_values: {
      evidence_text: "Potency improved in the follow-up assay.",
      source_locator: "page 4",
    },
  },
  content_hash: "b".repeat(64),
  sequence: 2,
};

const diff = [{
  object_id: paperId,
  object_kind: "paper",
  base_revision_id: baseRevisionId,
  proposed_revision_id: proposedRevisionId,
  change_type: "update",
  changes: [
    {
      path: "/normalized_values/title_guess",
      category: "text",
      before_present: true,
      after_present: true,
      before: "原始标题",
      after: "修订后的标题",
    },
  ],
}];

const scientificWorkspace = {
  workspace_version: draft.version,
  changeset: {
    id: draft.id,
    review_task_id: draft.review_task_id,
    paper_id: draft.paper_id,
    owner_id: draft.owner_id,
    base_release_id: draft.base_release_id,
    workflow_state: draft.workflow_state,
    version: draft.version,
    title: draft.title,
    reason: draft.reason,
  },
  paper: {
    id: draft.paper_id,
    paper_key: "paper-25",
    title: "Scientific workspace Paper",
    base_release_id: draft.base_release_id,
  },
  progress: {
    scope_count: 1,
    resolved_count: 1,
    blocker_count: 0,
    by_kind: { paper: { total: 1, resolved: 1, blockers: 0 } },
  },
  document: {
    url: `/api/v1/papers/${draft.paper_id}/source-pdf?kind=article&release_id=${draft.base_release_id}`,
    release_id: draft.base_release_id,
  },
  pages: [],
  regions: [],
  visual_objects: [],
  molecule_proposals: [],
  structures: [],
  evidence: [],
  assets: [],
  source_locators: [],
  attestation: null,
  scope: {
    id: "90000000-0000-4000-8000-000000000001",
    scope_hash: "d".repeat(64),
    item_count: 1,
  },
};

describe("Reviewer task and changeset workflow", () => {
  beforeEach(() => {
    const pinia = createPinia();
    setActivePinia(pinia);
    useAuthStore().acceptSession({
      user: {
        username: "reviewer.one",
        display_name: "核查员一",
        role: "reviewer",
        must_change_password: false,
      },
      csrf_token: "reviewer-csrf",
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("shows an actionable queue with separate start and resume paths", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/review/tasks") return jsonResponse(200, tasks);
      if (path === "/api/v1/review/changesets") return jsonResponse(200, [draft]);
      return jsonResponse(404, {
        code: "RESOURCE_NOT_FOUND",
        message: "Resource not found",
        details: {},
        request_id: "review-ui-request",
      });
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/review/tasks");
    await router.isReady();

    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.get("h1").text()).toBe("核查任务");
    expect(wrapper.get(".task-list-page").classes()).toContain("review-workspace");
    expect(wrapper.get(".task-table-section").classes()).toContain("panel");
    expect(wrapper.get(".task-table").classes()).toContain("data-table");
    expect(wrapper.get("[data-review-task] [data-status]").classes()).toContain("status-chip");
    expect(wrapper.findAll("[data-review-task]")).toHaveLength(2);
    expect(wrapper.get(`[data-task-id='${openTaskId}']`).text()).toContain("高优先级");
    expect(wrapper.get(`[data-task-id='${openTaskId}']`).text()).toContain("开始核查");
    const resume = wrapper.get(`[data-task-id='${activeTaskId}'] a`);
    expect(resume.text()).toContain("继续核查");
    expect(resume.attributes("href")).toBe(`/review/changesets/${changesetId}`);
  });

  it("reviews first-page molecule objects inside the existing task queue", async () => {
    const visualId = "91000000-0000-4000-8000-000000000001";
    const proposalId = "92000000-0000-4000-8000-000000000001";
    const regionId = "93000000-0000-4000-8000-000000000001";
    const assetId = "94000000-0000-4000-8000-000000000001";
    const queuePayload = {
      items: [
        {
          paper_id: tasks[1].paper_id,
          paper_key: "paper-25",
          base_release_id: releaseId,
          review_task_id: activeTaskId,
          changeset_id: changesetId,
          changeset_version: 3,
          visual_object: {
            id: visualId,
            object_key: "first-page-object-1",
            object_type: "complete_molecule",
            region_id: regionId,
          },
          proposal: {
            id: proposalId,
            proposal_key: "ocsr-1",
            disposition: "pending",
            revision_id: baseRevisionId,
          },
          crop_asset: {
            id: assetId,
            url: `/api/v1/assets/${assetId}/content`,
            original_filename: "molecule-crop.png",
            sha256: "c".repeat(64),
            byte_size: 1024,
            mime_type: "image/png",
            width: 240,
            height: 160,
            page_count: null,
            category: "ocsr_input",
            access_level: "reviewer",
          },
          page: 1,
          state: "proposal_review",
          blocking: true,
          reasons: ["proposal_pending"],
          paper_progress: { scope_count: 12, resolved_count: 11, blocker_count: 1 },
          deep_link: { view: "ocsr", page: 1, object: visualId, proposal: proposalId },
          priority: 40,
        },
        {
          paper_id: paperId,
          paper_key: "paper-24",
          base_release_id: releaseId,
          review_task_id: openTaskId,
          changeset_id: null,
          changeset_version: null,
          visual_object: {
            id: "91000000-0000-4000-8000-000000000002",
            object_key: "first-page-object-2",
            object_type: "non_structure",
            region_id: "93000000-0000-4000-8000-000000000002",
          },
          proposal: null,
          crop_asset: null,
          page: 1,
          state: "complete",
          blocking: false,
          reasons: [],
          paper_progress: { scope_count: 4, resolved_count: 4, blocker_count: 0 },
          deep_link: {
            view: "ocsr",
            page: 1,
            object: "91000000-0000-4000-8000-000000000002",
            proposal: null,
          },
          priority: 90,
        },
      ],
      next_cursor: null,
      status_counts: {
        localization_or_split: 0,
        needs_ocsr: 0,
        proposal_review: 1,
        source_or_attachment: 0,
        structure_assembly: 0,
        complete: 1,
      },
      pagination: { limit: 50, returned: 2 },
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/review/tasks") return jsonResponse(200, tasks);
      if (path === "/api/v1/review/changesets") return jsonResponse(200, [draft]);
      if (path === "/api/v1/review/tasks/first-page-molecule-objects") {
        return jsonResponse(200, queuePayload);
      }
      return jsonResponse(404, {
        code: "RESOURCE_NOT_FOUND",
        message: "Resource not found",
        details: {},
        request_id: "review-ui-request",
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const router = createAppRouter(createMemoryHistory());
    await router.push("/review/tasks?tab=molecules");
    await router.isReady();

    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.findAll("[role='tab']")).toHaveLength(2);
    expect(wrapper.get("[role='tab'][aria-selected='true']").text()).toContain("分子对象");
    expect(wrapper.get("[data-molecule-queue]").classes()).toContain("panel");
    expect(wrapper.get("[data-queue-counts]").text()).toContain("待审核 1");
    expect(wrapper.get("[data-molecule-row]").text()).toContain("paper-25");
    expect(wrapper.get("[data-molecule-row]").text()).toContain("11 / 12");
    expect(wrapper.get("[data-molecule-row] img").attributes("alt")).toContain(
      "paper-25 的分子对象裁剪图",
    );
    expect(wrapper.get("[data-molecule-row] a").attributes("href")).toBe(
      `/review/changesets/${changesetId}?view=ocsr&page=1&object=${visualId}&proposal=${proposalId}`,
    );
    expect(wrapper.get("[data-completed-group]").attributes("open")).toBeUndefined();
    expect(wrapper.text()).not.toContain("对象已核验");
    expect(fetchMock.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);

    await wrapper.get("select[name='queue-status']").setValue("complete");
    await flushPromises();
    expect(router.currentRoute.value.query.status).toBe("complete");
  });

  it("lists accessible changesets when opened without a task query", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/review/tasks") return jsonResponse(200, tasks);
      if (path === "/api/v1/review/changesets") return jsonResponse(200, [draft]);
      return jsonResponse(404, {
        code: "RESOURCE_NOT_FOUND",
        message: "Resource not found",
        details: {},
        request_id: "review-ui-request",
      });
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/review/changesets");
    await router.isReady();

    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.get("h1").text()).toBe("修改集");
    expect(wrapper.get(".changeset-index-page").classes()).toContain("review-workspace");
    expect(wrapper.get(".changeset-table-wrap").classes()).toContain("panel");
    expect(wrapper.findAll("[data-changeset-row]")).toHaveLength(1);
    expect(wrapper.get("[data-changeset-row]").text()).toContain(draft.title);
    expect(wrapper.get("[data-changeset-row] a").attributes("href")).toBe(`/review/changesets/${changesetId}`);
  });

  it("keeps the selected task aligned when an earlier Paper load finishes late", async () => {
    const secondPaperId = "20000000-0000-4000-8000-000000000003";
    const secondTaskId = "50000000-0000-4000-8000-000000000003";
    const taskA = { ...tasks[0], id: openTaskId, paper_id: paperId };
    const taskB = { ...tasks[0], id: secondTaskId, paper_id: secondPaperId };
    const paperPayload = (id: string, key: string, title: string) => ({
      request_id: "review-ui-request",
      release: {
        id: releaseId,
        key: "baseline-2026-09-12",
        title: "LeadTrace baseline",
        published_at: "2026-09-12T00:00:00Z",
        verification_status: "unverified",
      },
      paper: {
        id,
        revision_id: baseRevisionId,
        paper_key: key,
        doi: null,
        title,
        year: "2026",
        target: "Kinase A",
        review_status: "unreviewed",
      },
      compounds: [],
      lineages: [],
      lineage_edges: [],
      structures: [],
      evidence: [],
      activities: [],
      quality_summary: {
        relations: { resolved: 0, total: 0 },
        structures: { confirmed: 0, total: 0 },
        pair_ready: { eligible: 0, total: 0 },
        human_review: { reviewed: 0, total: 1 },
      },
    });
    let resolvePaperA: ((response: Response) => void) | undefined;
    const delayedPaperA = new Promise<Response>((resolve) => { resolvePaperA = resolve; });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/review/tasks") return jsonResponse(200, [taskA, taskB]);
      if (path === "/api/v1/review/changesets") return jsonResponse(200, []);
      if (path === `/api/v1/papers/${paperId}`) return delayedPaperA;
      if (path === `/api/v1/papers/${secondPaperId}`) {
        return jsonResponse(200, paperPayload(secondPaperId, "paper-b", "Paper B title"));
      }
      return jsonResponse(404, {
        code: "RESOURCE_NOT_FOUND",
        message: "Resource not found",
        details: {},
        request_id: "review-ui-request",
      });
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/changesets?task=${openTaskId}`);
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await new Promise((resolve) => setTimeout(resolve, 0));

    await router.push(`/review/changesets?task=${secondTaskId}`);
    await flushPromises();
    expect(wrapper.text()).toContain("Paper B title");

    resolvePaperA?.(jsonResponse(200, paperPayload(paperId, "paper-a", "Paper A title")));
    await flushPromises();

    expect(router.currentRoute.value.query.task).toBe(secondTaskId);
    expect(wrapper.text()).toContain("Paper B title");
    expect(wrapper.text()).not.toContain("Paper A title");
    expect(wrapper.get("#new-changeset-title").element).toHaveProperty(
      "value",
      "核查 paper-b 的文献元数据与证据",
    );
  });

  it("renders a versioned draft editor and structured diff summary", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === `/api/v1/review/changesets/${changesetId}`) return jsonResponse(200, draft);
      if (path === `/api/v1/review/changesets/${changesetId}/items`) return jsonResponse(200, [item, evidenceItem]);
      if (path === `/api/v1/review/changesets/${changesetId}/diff`) return jsonResponse(200, diff);
      return jsonResponse(404, {
        code: "RESOURCE_NOT_FOUND",
        message: "Resource not found",
        details: {},
        request_id: "review-ui-request",
      });
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/changesets/${changesetId}`);
    await router.isReady();

    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.get("h1").text()).toBe("核查修改集");
    expect(wrapper.get(".changeset-page").classes()).toContain("review-workspace");
    expect(wrapper.get(".workspace-tabs").classes()).toContain("workspace-toolbar");
    expect(wrapper.get(".metadata-editor").classes()).toContain("panel");
    expect(wrapper.get("#changeset-title").element).toHaveProperty("value", draft.title);
    expect(wrapper.get("#changeset-reason").element).toHaveProperty("value", draft.reason);
    expect(wrapper.get("[data-changeset-version]").text()).toContain("版本 3");
    expect(wrapper.get("[data-item-editor] textarea").element).toHaveProperty(
      "value",
      expect.stringContaining("修订后的标题"),
    );
    await wrapper.get("[aria-label='修改集视图'] button:nth-child(2)").trigger("click");
    expect(wrapper.get("[data-diff-summary]").text()).toContain("标题");
    expect(wrapper.get("[data-diff-summary]").text()).toContain("原始标题");
    expect(wrapper.get("[data-diff-summary]").text()).toContain("修订后的标题");
  });

  it("integrates the scientific Paper workspace at the existing changeset route", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === `/api/v1/review/changesets/${changesetId}`) return jsonResponse(200, draft);
      if (path === `/api/v1/review/changesets/${changesetId}/items`) return jsonResponse(200, [item]);
      if (path === `/api/v1/review/changesets/${changesetId}/diff`) return jsonResponse(200, diff);
      if (path === `/api/v1/review/changesets/${changesetId}/workspace`) {
        return jsonResponse(200, scientificWorkspace);
      }
      return jsonResponse(404, {
        code: "RESOURCE_NOT_FOUND",
        message: "Resource not found",
        details: {},
        request_id: "review-ui-request",
      });
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/changesets/${changesetId}?view=overview`);
    await router.isReady();

    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.find("[data-paper-workspace]").exists()).toBe(true);
    expect(wrapper.find("[data-legacy-workspace]").exists()).toBe(false);
    expect(wrapper.findAll("[data-workspace-tabs] button")).toHaveLength(7);
    expect(wrapper.get("[data-paper-workspace]").text()).toContain("Scientific workspace Paper");
  });

  it("keeps the newest workspace when an earlier route load finishes late", async () => {
    const nextChangesetId = "60000000-0000-4000-8000-000000000002";
    const nextDraft = {
      ...draft,
      id: nextChangesetId,
      title: "第二个核查工作区",
      version: 7,
    };
    const nextItem = {
      ...item,
      id: "70000000-0000-4000-8000-000000000003",
      changeset_id: nextChangesetId,
      changeset_version: 7,
    };
    let resolveEarlierLoad: ((response: Response) => void) | undefined;
    const earlierLoad = new Promise<Response>((resolve) => {
      resolveEarlierLoad = resolve;
    });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === `/api/v1/review/changesets/${changesetId}`) return earlierLoad;
      if (path === `/api/v1/review/changesets/${changesetId}/items`) return jsonResponse(200, [item]);
      if (path === `/api/v1/review/changesets/${changesetId}/diff`) return jsonResponse(200, diff);
      if (path === `/api/v1/review/changesets/${nextChangesetId}`) return jsonResponse(200, nextDraft);
      if (path === `/api/v1/review/changesets/${nextChangesetId}/items`) return jsonResponse(200, [nextItem]);
      if (path === `/api/v1/review/changesets/${nextChangesetId}/diff`) return jsonResponse(200, []);
      return jsonResponse(404, {
        code: "RESOURCE_NOT_FOUND",
        message: "Resource not found",
        details: {},
        request_id: "review-ui-request",
      });
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/changesets/${changesetId}`);
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await new Promise((resolve) => setTimeout(resolve, 0));

    await router.push(`/review/changesets/${nextChangesetId}`);
    await flushPromises();
    expect(wrapper.get("#changeset-title").element).toHaveProperty("value", nextDraft.title);

    resolveEarlierLoad?.(jsonResponse(200, draft));
    await flushPromises();

    expect(router.currentRoute.value.params.changesetId).toBe(nextChangesetId);
    expect(wrapper.get("#changeset-title").element).toHaveProperty("value", nextDraft.title);
    expect(wrapper.get("[data-changeset-version]").text()).toContain("版本 7");
  });

  it("retries a torn workspace read before editing the latest version", async () => {
    const latestDraft = { ...draft, version: 4 };
    const latestItem = {
      ...item,
      changeset_version: 4,
      proposed_snapshot: { normalized_values: { title_guess: "其他会话的最新标题" } },
    };
    let itemReads = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === `/api/v1/review/changesets/${changesetId}`) {
        return jsonResponse(200, latestDraft);
      }
      if (path === `/api/v1/review/changesets/${changesetId}/items`) {
        itemReads += 1;
        return jsonResponse(200, itemReads === 1 ? [item] : [latestItem]);
      }
      if (path === `/api/v1/review/changesets/${changesetId}/diff`) {
        return jsonResponse(200, diff);
      }
      return jsonResponse(404, {
        code: "RESOURCE_NOT_FOUND",
        message: "Resource not found",
        details: {},
        request_id: "review-ui-request",
      });
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/changesets/${changesetId}`);
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    expect(itemReads).toBe(2);
    expect(wrapper.get("[data-changeset-version]").text()).toContain("版本 4");
    expect(wrapper.get("#paper-title-field").element).toHaveProperty(
      "value",
      "其他会话的最新标题",
    );
  });

  it("does not let an earlier autosave response mutate a newly opened workspace", async () => {
    const nextChangesetId = "60000000-0000-4000-8000-000000000002";
    const nextDraft = { ...draft, id: nextChangesetId, title: "第二个核查工作区", version: 7 };
    const nextItem = {
      ...item,
      id: "70000000-0000-4000-8000-000000000003",
      changeset_id: nextChangesetId,
      changeset_version: 7,
      proposed_snapshot: { normalized_values: { title_guess: "第二个工作区标题" } },
    };
    let resolveAutosave: ((response: Response) => void) | undefined;
    let markAutosaveStarted: (() => void) | undefined;
    const autosaveStarted = new Promise<void>((resolve) => { markAutosaveStarted = resolve; });
    const delayedAutosave = new Promise<Response>((resolve) => { resolveAutosave = resolve; });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === `/api/v1/review/changesets/${changesetId}`) return jsonResponse(200, draft);
      if (path === `/api/v1/review/changesets/${changesetId}/items` && !init?.method) return jsonResponse(200, [item]);
      if (path === `/api/v1/review/changesets/${changesetId}/diff`) return jsonResponse(200, diff);
      if (path === `/api/v1/review/changesets/${changesetId}/items/${itemId}` && init?.method === "PATCH") {
        markAutosaveStarted?.();
        return delayedAutosave;
      }
      if (path === `/api/v1/review/changesets/${nextChangesetId}`) return jsonResponse(200, nextDraft);
      if (path === `/api/v1/review/changesets/${nextChangesetId}/items`) return jsonResponse(200, [nextItem]);
      if (path === `/api/v1/review/changesets/${nextChangesetId}/diff`) return jsonResponse(200, []);
      return jsonResponse(404, {
        code: "RESOURCE_NOT_FOUND",
        message: "Resource not found",
        details: {},
        request_id: "review-ui-request",
      });
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/changesets/${changesetId}`);
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    await wrapper.get("#paper-title-field").setValue("第一个工作区的延迟保存");
    await autosaveStarted;
    await router.push(`/review/changesets/${nextChangesetId}`);
    await flushPromises();
    expect(wrapper.get("#changeset-title").element).toHaveProperty("value", nextDraft.title);

    resolveAutosave?.(jsonResponse(200, {
      ...item,
      proposed_snapshot: { normalized_values: { title_guess: "第一个工作区的延迟保存" } },
      changeset_version: 4,
    }));
    await flushPromises();

    expect(wrapper.get("#changeset-title").element).toHaveProperty("value", nextDraft.title);
    expect(wrapper.get("#paper-title-field").element).toHaveProperty("value", "第二个工作区标题");
    expect(wrapper.get("[data-changeset-version]").text()).toContain("版本 7");
  });

  it("does not let a delayed submission response replace a newly opened workspace", async () => {
    const nextChangesetId = "60000000-0000-4000-8000-000000000002";
    const nextDraft = { ...draft, id: nextChangesetId, title: "第二个核查工作区", version: 7 };
    const nextItem = {
      ...item,
      id: "70000000-0000-4000-8000-000000000003",
      changeset_id: nextChangesetId,
      changeset_version: 7,
    };
    let resolveSubmission: ((response: Response) => void) | undefined;
    let markSubmissionStarted: (() => void) | undefined;
    const submissionStarted = new Promise<void>((resolve) => { markSubmissionStarted = resolve; });
    const delayedSubmission = new Promise<Response>((resolve) => { resolveSubmission = resolve; });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === `/api/v1/review/changesets/${changesetId}`) return jsonResponse(200, draft);
      if (path === `/api/v1/review/changesets/${changesetId}/items`) return jsonResponse(200, [item]);
      if (path === `/api/v1/review/changesets/${changesetId}/diff`) return jsonResponse(200, diff);
      if (path === `/api/v1/review/changesets/${changesetId}/submit` && init?.method === "POST") {
        markSubmissionStarted?.();
        return delayedSubmission;
      }
      if (path === `/api/v1/review/changesets/${nextChangesetId}`) return jsonResponse(200, nextDraft);
      if (path === `/api/v1/review/changesets/${nextChangesetId}/items`) return jsonResponse(200, [nextItem]);
      if (path === `/api/v1/review/changesets/${nextChangesetId}/diff`) return jsonResponse(200, []);
      return jsonResponse(404, {
        code: "RESOURCE_NOT_FOUND",
        message: "Resource not found",
        details: {},
        request_id: "review-ui-request",
      });
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/changesets/${changesetId}`);
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    await wrapper.get("[aria-label='修改集视图'] button:nth-child(3)").trigger("click");
    await wrapper.get(".submit-button").trigger("click");
    await submissionStarted;
    await router.push(`/review/changesets/${nextChangesetId}`);
    await flushPromises();

    resolveSubmission?.(jsonResponse(200, {
      ...draft,
      workflow_state: "submitted",
      version: 4,
      submitted_snapshot: { item_ids: [itemId] },
      submitted_at: "2026-09-12T03:00:00Z",
    }));
    await flushPromises();

    expect(wrapper.get("[data-changeset-version]").text()).toContain("版本 7");
    expect(wrapper.get("#changeset-title").element).toHaveProperty("value", nextDraft.title);
  });

  it("provides focused Paper metadata and evidence text controls", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === `/api/v1/review/changesets/${changesetId}`) return jsonResponse(200, draft);
      if (path === `/api/v1/review/changesets/${changesetId}/items`) return jsonResponse(200, [item, evidenceItem]);
      if (path === `/api/v1/review/changesets/${changesetId}/diff`) return jsonResponse(200, diff);
      return jsonResponse(404, {
        code: "RESOURCE_NOT_FOUND",
        message: "Resource not found",
        details: {},
        request_id: "review-ui-request",
      });
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/changesets/${changesetId}`);
    await router.isReady();

    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.get("#paper-title-field").element).toHaveProperty("value", "修订后的标题");
    expect(wrapper.get("[data-evidence-editor] textarea").element).toHaveProperty(
      "value",
      "Potency improved in the follow-up assay.",
    );
    expect(wrapper.get("[data-paper-editor]").text()).toContain("文献元数据");
    expect(wrapper.get("[data-evidence-editor]").text()).toContain("证据文本");
  });

  it("autosaves focused field edits through the versioned item endpoint", async () => {
    const requests: Array<Record<string, unknown>> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === `/api/v1/review/changesets/${changesetId}`) return jsonResponse(200, draft);
      if (path === `/api/v1/review/changesets/${changesetId}/items` && !init?.method) {
        return jsonResponse(200, [item, evidenceItem]);
      }
      if (path === `/api/v1/review/changesets/${changesetId}/diff`) return jsonResponse(200, diff);
      if (path === `/api/v1/review/changesets/${changesetId}/items/${itemId}` && init?.method === "PATCH") {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        requests.push(body);
        return jsonResponse(200, {
          ...item,
          proposed_snapshot: body.proposed_snapshot,
          changeset_version: 4,
        });
      }
      return jsonResponse(404, {
        code: "RESOURCE_NOT_FOUND",
        message: "Resource not found",
        details: {},
        request_id: "review-ui-request",
      });
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/changesets/${changesetId}`);
    await router.isReady();

    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();
    await wrapper.get("#paper-title-field").setValue("经人工核查的标题");

    expect(wrapper.get("[data-save-state]").attributes("data-save-state")).toBe("pending");
    await new Promise((resolve) => setTimeout(resolve, 750));
    await flushPromises();

    expect(requests).toHaveLength(1);
    expect(requests[0]).toMatchObject({
      expected_version: 3,
      proposed_snapshot: {
        normalized_values: {
          title_guess: "经人工核查的标题",
          year: "2026",
          target: "Kinase A",
          review_status: "unreviewed",
        },
      },
    });
    expect(wrapper.get("[data-save-state]").attributes("data-save-state")).toBe("saved");
    expect(wrapper.get("[data-changeset-version]").text()).toContain("版本 4");
  });

  it("does not overlay an immutable submission with a stale local recovery buffer", async () => {
    localStorage.setItem(reviewerAutosaveKey, JSON.stringify({
      title: "不应恢复的本机标题",
      reason: "不应恢复的本机原因",
      itemJson: {
        [itemId]: JSON.stringify({ normalized_values: { title_guess: "不应显示的草稿标题" } }),
      },
    }));
    const submitted = {
      ...draft,
      workflow_state: "submitted",
      version: 4,
      submitted_snapshot: { item_ids: [itemId] },
      submitted_at: "2026-09-12T03:00:00Z",
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === `/api/v1/review/changesets/${changesetId}`) return jsonResponse(200, submitted);
      if (path === `/api/v1/review/changesets/${changesetId}/items`) {
        return jsonResponse(200, [{ ...item, changeset_version: submitted.version }]);
      }
      if (path === `/api/v1/review/changesets/${changesetId}/diff`) return jsonResponse(200, diff);
      return jsonResponse(404, {
        code: "RESOURCE_NOT_FOUND",
        message: "Resource not found",
        details: {},
        request_id: "review-ui-request",
      });
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/changesets/${changesetId}`);
    await router.isReady();

    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.find("[data-recovery-buffer]").exists()).toBe(false);
    expect(wrapper.get("#changeset-title").element).toHaveProperty("value", draft.title);
    expect(wrapper.get("#paper-title-field").element).toHaveProperty("value", "修订后的标题");
    expect(wrapper.get("#paper-title-field").attributes("readonly")).toBeDefined();
    expect(localStorage.getItem(reviewerAutosaveKey)).toBeNull();
  });

  it("does not restore an unscoped draft buffer after an account switch", async () => {
    localStorage.setItem(`leadtrace:review:autosave:${changesetId}`, JSON.stringify({
      title: "其他账号遗留的本机标题",
      reason: "其他账号遗留的本机原因",
      itemJson: {
        [itemId]: JSON.stringify({ normalized_values: { title_guess: "其他账号的草稿标题" } }),
      },
    }));
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === `/api/v1/review/changesets/${changesetId}`) return jsonResponse(200, draft);
      if (path === `/api/v1/review/changesets/${changesetId}/items`) return jsonResponse(200, [item]);
      if (path === `/api/v1/review/changesets/${changesetId}/diff`) return jsonResponse(200, diff);
      return jsonResponse(404, {
        code: "RESOURCE_NOT_FOUND",
        message: "Resource not found",
        details: {},
        request_id: "review-ui-request",
      });
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/changesets/${changesetId}`);
    await router.isReady();

    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.find("[data-recovery-buffer]").exists()).toBe(false);
    expect(wrapper.get("#changeset-title").element).toHaveProperty("value", draft.title);
    expect(wrapper.get("#paper-title-field").element).toHaveProperty("value", "修订后的标题");
  });

  it("restores and reschedules a valid local draft buffer after reload", async () => {
    const recoveredSnapshot = {
      normalized_values: {
        title_guess: "断网期间核查的标题",
        year: "2026",
        target: "Kinase A",
        review_status: "unreviewed",
      },
    };
    localStorage.setItem(reviewerAutosaveKey, JSON.stringify({
      baseVersion: 3,
      title: draft.title,
      reason: draft.reason,
      itemJson: { [itemId]: JSON.stringify(recoveredSnapshot, null, 2) },
    }));
    const requests: Array<Record<string, unknown>> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === `/api/v1/review/changesets/${changesetId}`) return jsonResponse(200, draft);
      if (path === `/api/v1/review/changesets/${changesetId}/items` && !init?.method) {
        return jsonResponse(200, [item]);
      }
      if (path === `/api/v1/review/changesets/${changesetId}/diff`) return jsonResponse(200, diff);
      if (path === `/api/v1/review/changesets/${changesetId}/items/${itemId}` && init?.method === "PATCH") {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        requests.push(body);
        return jsonResponse(200, {
          ...item,
          proposed_snapshot: body.proposed_snapshot,
          changeset_version: 4,
        });
      }
      return jsonResponse(404, {
        code: "RESOURCE_NOT_FOUND",
        message: "Resource not found",
        details: {},
        request_id: "review-ui-request",
      });
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/changesets/${changesetId}`);
    await router.isReady();

    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.get("[data-recovery-buffer]").text()).toContain("已恢复本机尚未同步的修改");
    expect(wrapper.get("#paper-title-field").element).toHaveProperty("value", "断网期间核查的标题");
    expect(wrapper.get("[data-save-state]").attributes("data-save-state")).toBe("pending");
    await new Promise((resolve) => setTimeout(resolve, 750));
    await flushPromises();
    expect(requests).toHaveLength(1);
    expect(wrapper.get("[data-save-state]").attributes("data-save-state")).toBe("saved");
    expect(wrapper.find("[data-recovery-buffer]").exists()).toBe(false);
  });

  it("requires explicit conflict resolution for recovery based on an older version", async () => {
    const recoveryBase = {
      title: "版本 2 的服务端标题",
      reason: draft.reason,
      itemJson: {
        [itemId]: JSON.stringify({ normalized_values: { title_guess: "版本 2 的服务端内容" } }),
      },
    };
    localStorage.setItem(reviewerAutosaveKey, JSON.stringify({
      baseVersion: 2,
      base: recoveryBase,
      title: "版本 2 的本机标题",
      reason: draft.reason,
      itemJson: {
        [itemId]: JSON.stringify({ normalized_values: { title_guess: "版本 2 的草稿内容" } }),
      },
    }));
    const writes: Array<{ path: string; body: Record<string, unknown> }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === `/api/v1/review/changesets/${changesetId}` && !init?.method) {
        return jsonResponse(200, draft);
      }
      if (path === `/api/v1/review/changesets/${changesetId}/items` && !init?.method) {
        return jsonResponse(200, [item]);
      }
      if (path === `/api/v1/review/changesets/${changesetId}/diff`) return jsonResponse(200, diff);
      if (path === `/api/v1/review/changesets/${changesetId}` && init?.method === "PATCH") {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        writes.push({ path, body });
        return jsonResponse(200, { ...draft, ...body, version: 4 });
      }
      return jsonResponse(404, {
        code: "RESOURCE_NOT_FOUND",
        message: "Resource not found",
        details: {},
        request_id: "review-ui-request",
      });
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/changesets/${changesetId}`);
    await router.isReady();

    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.find("[data-recovery-buffer]").exists()).toBe(false);
    expect(wrapper.get("#changeset-title").element).toHaveProperty("value", draft.title);
    expect(wrapper.get("#paper-title-field").element).toHaveProperty("value", "修订后的标题");
    const resolver = wrapper.get("[data-conflict-resolver]");
    expect(resolver.text()).toContain("本地基于版本2");
    expect(resolver.text()).toContain("服务端当前版本3");
    expect(resolver.text()).toContain("修改集标题");
    expect(resolver.text()).toContain("版本 2 的本机标题");
    expect(resolver.text()).toContain(draft.title);
    expect(resolver.text()).toContain("title_guess");
    expect(resolver.get("[data-apply-merge]").attributes("disabled")).toBeDefined();
    expect(localStorage.getItem(reviewerAutosaveKey)).toContain("版本 2 的草稿内容");

    const conflicts = resolver.findAll("[data-merge-conflict]");
    const itemConflict = conflicts.find((entry) => entry.text().includes("title_guess"));
    const titleConflict = conflicts.find((entry) => entry.text().includes("修改集标题"));
    expect(itemConflict).toBeDefined();
    expect(titleConflict).toBeDefined();
    await itemConflict!.findAll("button")[1].trigger("click");
    expect(resolver.get("[data-apply-merge]").attributes("disabled")).toBeDefined();
    await titleConflict!.findAll("button")[0].trigger("click");
    expect(resolver.get("[data-apply-merge]").attributes("disabled")).toBeUndefined();
    await resolver.get("[data-apply-merge]").trigger("click");
    await new Promise((resolve) => setTimeout(resolve, 750));
    await flushPromises();

    expect(writes).toEqual([{
      path: `/api/v1/review/changesets/${changesetId}`,
      body: {
        expected_version: 3,
        title: "版本 2 的本机标题",
        reason: draft.reason,
      },
    }]);
    expect(wrapper.get("#paper-title-field").element).toHaveProperty("value", "修订后的标题");
  });

  it("merges disjoint recovery and server edits without overwriting either side", async () => {
    const serverDraft = {
      ...draft,
      title: "版本 2 的服务端标题",
      reason: "服务端补充的修改原因",
      version: 3,
    };
    const baseSnapshot = {
      normalized_values: {
        title_guess: "版本 2 的服务端内容",
        target: "Kinase A",
      },
    };
    const serverItem = {
      ...item,
      proposed_snapshot: {
        normalized_values: {
          title_guess: "版本 2 的服务端内容",
          target: "Kinase B",
        },
      },
    };
    localStorage.setItem(reviewerAutosaveKey, JSON.stringify({
      baseVersion: 2,
      base: {
        title: "版本 2 的服务端标题",
        reason: draft.reason,
        itemJson: { [itemId]: JSON.stringify(baseSnapshot) },
      },
      title: "本机修订的标题",
      reason: draft.reason,
      itemJson: { [itemId]: JSON.stringify(baseSnapshot) },
    }));
    const writes: Array<{ path: string; body: Record<string, unknown> }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === `/api/v1/review/changesets/${changesetId}` && !init?.method) {
        return jsonResponse(200, serverDraft);
      }
      if (path === `/api/v1/review/changesets/${changesetId}/items` && !init?.method) {
        return jsonResponse(200, [serverItem]);
      }
      if (path === `/api/v1/review/changesets/${changesetId}/diff`) return jsonResponse(200, diff);
      if (path === `/api/v1/review/changesets/${changesetId}` && init?.method === "PATCH") {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        writes.push({ path, body });
        return jsonResponse(200, { ...serverDraft, ...body, version: 4 });
      }
      if (path.includes("/items/") && init?.method === "PATCH") {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        writes.push({ path, body });
        return jsonResponse(200, { ...serverItem, proposed_snapshot: body.proposed_snapshot, changeset_version: 5 });
      }
      return jsonResponse(404, {
        code: "RESOURCE_NOT_FOUND",
        message: "Resource not found",
        details: {},
        request_id: "review-ui-request",
      });
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/changesets/${changesetId}`);
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    const resolver = wrapper.get("[data-conflict-resolver]");
    expect(resolver.text()).toContain("没有同字段冲突");
    await resolver.get("[data-apply-merge]").trigger("click");
    await new Promise((resolve) => setTimeout(resolve, 750));
    await flushPromises();

    expect(writes).toEqual([{
      path: `/api/v1/review/changesets/${changesetId}`,
      body: {
        expected_version: 3,
        title: "本机修订的标题",
        reason: "服务端补充的修改原因",
      },
    }]);
    expect(wrapper.get("#paper-target-field").element).toHaveProperty("value", "Kinase B");
  });

  it("shows expected and current versions when an autosave receives a 409", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === `/api/v1/review/changesets/${changesetId}`) return jsonResponse(200, draft);
      if (path === `/api/v1/review/changesets/${changesetId}/items` && !init?.method) {
        return jsonResponse(200, [item]);
      }
      if (path === `/api/v1/review/changesets/${changesetId}/diff`) return jsonResponse(200, diff);
      if (path === `/api/v1/review/changesets/${changesetId}/items/${itemId}` && init?.method === "PATCH") {
        return jsonResponse(409, {
          code: "REVISION_CONFLICT",
          message: "Changeset version conflict",
          details: { expected_version: 3, current_version: 5 },
          request_id: "stale-review-save",
        });
      }
      return jsonResponse(404, {
        code: "RESOURCE_NOT_FOUND",
        message: "Resource not found",
        details: {},
        request_id: "review-ui-request",
      });
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/changesets/${changesetId}`);
    await router.isReady();

    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();
    await wrapper.get("#paper-title-field").setValue("发生冲突的标题");
    await new Promise((resolve) => setTimeout(resolve, 750));
    await flushPromises();

    expect(wrapper.get("[data-save-state]").attributes("data-save-state")).toBe("conflict");
    const resolver = wrapper.get("[data-conflict-resolver]");
    expect(resolver.text()).toContain("本地基于版本3");
    expect(resolver.text()).toContain("服务端当前版本5");
    expect(resolver.text()).toContain("stale-review-save");
    expect(localStorage.getItem(reviewerAutosaveKey)).toContain("发生冲突的标题");
  });

  it("blocks submission when the structured diff contains no changes", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === `/api/v1/review/changesets/${changesetId}`) return jsonResponse(200, draft);
      if (path === `/api/v1/review/changesets/${changesetId}/items`) return jsonResponse(200, [item]);
      if (path === `/api/v1/review/changesets/${changesetId}/diff`) return jsonResponse(200, []);
      return jsonResponse(404, {
        code: "RESOURCE_NOT_FOUND",
        message: "Resource not found",
        details: {},
        request_id: "review-ui-request",
      });
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/changesets/${changesetId}`);
    await router.isReady();

    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();
    await wrapper.get("[aria-label='修改集视图'] button:nth-child(3)").trigger("click");

    expect(wrapper.get("[data-submission-page]").text()).toContain("当前没有可提交的字段变更");
    expect(wrapper.get(".submit-button").attributes("disabled")).toBeDefined();
  });

  it("blocks submission while a full snapshot contains invalid JSON", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === `/api/v1/review/changesets/${changesetId}`) return jsonResponse(200, draft);
      if (path === `/api/v1/review/changesets/${changesetId}/items`) return jsonResponse(200, [item]);
      if (path === `/api/v1/review/changesets/${changesetId}/diff`) return jsonResponse(200, diff);
      return jsonResponse(404, {
        code: "RESOURCE_NOT_FOUND",
        message: "Resource not found",
        details: {},
        request_id: "review-ui-request",
      });
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/changesets/${changesetId}`);
    await router.isReady();

    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();
    await wrapper.get("[data-item-editor] textarea").setValue("{");
    await wrapper.get("[aria-label='修改集视图'] button:nth-child(3)").trigger("click");

    expect(wrapper.get("[data-submission-page]").text()).toContain("请先修正编辑器中的格式错误");
    expect(wrapper.get(".submit-button").attributes("disabled")).toBeDefined();
  });

  it("submits an immutable snapshot into pending Admin approval", async () => {
    const requests: Array<Record<string, unknown>> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === `/api/v1/review/changesets/${changesetId}` && !init?.method) {
        return jsonResponse(200, draft);
      }
      if (path === `/api/v1/review/changesets/${changesetId}/items`) return jsonResponse(200, [item, evidenceItem]);
      if (path === `/api/v1/review/changesets/${changesetId}/diff`) return jsonResponse(200, diff);
      if (path === `/api/v1/review/changesets/${changesetId}/submit` && init?.method === "POST") {
        requests.push(JSON.parse(String(init.body)) as Record<string, unknown>);
        return jsonResponse(200, {
          ...draft,
          workflow_state: "submitted",
          version: 4,
          submitted_snapshot: { item_ids: [itemId, evidenceItem.id] },
          submitted_at: "2026-09-12T03:00:00Z",
        });
      }
      return jsonResponse(404, {
        code: "RESOURCE_NOT_FOUND",
        message: "Resource not found",
        details: {},
        request_id: "review-ui-request",
      });
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/changesets/${changesetId}`);
    await router.isReady();

    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();
    await wrapper.get("[aria-label='修改集视图'] button:nth-child(3)").trigger("click");
    await wrapper.get(".submit-button").trigger("click");
    await flushPromises();

    expect(requests).toEqual([{ expected_version: 3 }]);
    expect(wrapper.get("[data-approval-state]").text()).toContain("已提交，等待管理员审批");
    expect(wrapper.get(".state-label").text()).toBe("待管理员审批");
    expect(wrapper.get("[data-changeset-version]").text()).toContain("版本 4");
    expect(wrapper.find(".submit-button").exists()).toBe(false);
    await wrapper.get("[aria-label='修改集视图'] button:nth-child(1)").trigger("click");
    expect(wrapper.get("#changeset-title").attributes("readonly")).toBeDefined();
    expect(wrapper.get("#paper-title-field").attributes("readonly")).toBeDefined();
    expect(wrapper.get("[data-evidence-editor] textarea").attributes("readonly")).toBeDefined();
  });

  it("requires an Admin reason before requesting changes and reopening a revision", async () => {
    useAuthStore().acceptSession({
      user: {
        username: "admin.one",
        display_name: "管理员一",
        role: "admin",
        must_change_password: false,
      },
      csrf_token: "admin-csrf",
    });
    const submitted = {
      ...draft,
      workflow_state: "submitted",
      version: 4,
      submitted_snapshot: { item_ids: [itemId] },
      submitted_at: "2026-09-12T03:00:00Z",
    };
    let serverChangeset = submitted;
    const requests: Array<{ path: string; body: Record<string, unknown> }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === `/api/v1/review/changesets/${changesetId}` && !init?.method) {
        return jsonResponse(200, serverChangeset);
      }
      if (path === `/api/v1/review/changesets/${changesetId}/items`) {
        return jsonResponse(200, [{
          ...item,
          changeset_version: serverChangeset.version,
        }]);
      }
      if (path === `/api/v1/review/changesets/${changesetId}/diff`) return jsonResponse(200, diff);
      if (path === `/api/v1/review/changesets/${changesetId}/request-changes` && init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        requests.push({ path, body });
        serverChangeset = { ...submitted, workflow_state: "changes_requested", version: 5 };
        return jsonResponse(200, serverChangeset);
      }
      if (path === `/api/v1/review/changesets/${changesetId}/revise` && init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        requests.push({ path, body });
        serverChangeset = {
          ...draft,
          workflow_state: "revised_draft",
          version: 6,
          submitted_snapshot: submitted.submitted_snapshot,
          submitted_at: submitted.submitted_at,
        };
        return jsonResponse(200, serverChangeset);
      }
      if (path === `/api/v1/review/changesets/${changesetId}/items/${itemId}` && init?.method === "PATCH") {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        requests.push({ path, body });
        return jsonResponse(200, {
          ...item,
          proposed_snapshot: body.proposed_snapshot,
          changeset_version: 7,
        });
      }
      return jsonResponse(404, {
        code: "RESOURCE_NOT_FOUND",
        message: "Resource not found",
        details: {},
        request_id: "review-ui-request",
      });
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/changesets/${changesetId}`);
    await router.isReady();

    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();
    await wrapper.get("[aria-label='修改集视图'] button:nth-child(3)").trigger("click");
    const requestChanges = wrapper.findAll("button").find((button) => button.text() === "要求修改");
    expect(requestChanges).toBeDefined();
    await requestChanges!.trigger("click");
    expect(wrapper.get(".field-error").text()).toContain("审批理由不能为空");
    expect(requests).toHaveLength(0);

    await wrapper.get("#decision-reason").setValue("证据文本需要保留原始限定词");
    await requestChanges!.trigger("click");
    await flushPromises();
    expect(wrapper.get("[data-approval-state]").text()).toContain("管理员要求修改");
    const reviseButton = wrapper.findAll("button").find((button) => button.text() === "重新开启草稿");
    await reviseButton!.trigger("click");
    await flushPromises();

    expect(requests).toEqual([
      {
        path: `/api/v1/review/changesets/${changesetId}/request-changes`,
        body: { expected_version: 4, reason: "证据文本需要保留原始限定词" },
      },
      {
        path: `/api/v1/review/changesets/${changesetId}/revise`,
        body: { expected_version: 5 },
      },
    ]);
    expect(wrapper.get("[data-changeset-version]").text()).toContain("版本 6");
    expect(wrapper.get("#paper-title-field").attributes("readonly")).toBeUndefined();
    await wrapper.get("#paper-title-field").setValue("管理员退回后修订的标题");
    await new Promise((resolve) => setTimeout(resolve, 750));
    await flushPromises();
    expect(requests.at(-1)).toEqual({
      path: `/api/v1/review/changesets/${changesetId}/items/${itemId}`,
      body: {
        expected_version: 6,
        proposed_snapshot: {
          normalized_values: {
            title_guess: "管理员退回后修订的标题",
            year: "2026",
            target: "Kinase A",
            review_status: "unreviewed",
          },
        },
      },
    });
  });

  it("keeps a local recovery buffer and surfaces optimistic-lock conflicts", async () => {
    const save = vi.fn(async () => {
      throw new Error("offline");
    });
    const autosave = createAutosave({
      key: "changeset-autosave",
      delayMs: 0,
      save,
    });

    autosave.schedule({ title: "本地未同步标题" });
    expect(autosave.recovery()).toEqual({ title: "本地未同步标题" });
    await new Promise((resolve) => setTimeout(resolve, 0));
    await flushPromises();
    expect(save).toHaveBeenCalledTimes(1);
    expect(autosave.state.value).toBe("offline");

    const successful = createAutosave({
      key: "changeset-autosave-success",
      delayMs: 0,
      save: async () => undefined,
    });
    successful.schedule({ title: "已写入服务端" });
    await new Promise((resolve) => setTimeout(resolve, 0));
    await flushPromises();
    expect(successful.state.value).toBe("saved");
    expect(successful.recovery()).toBeNull();

    const conflicted = createAutosave({
      key: "changeset-autosave-conflict",
      delayMs: 0,
      save: async () => {
        throw new ApiError(409, "REVISION_CONFLICT", "conflict-request", "conflict", {
          expected_version: 3,
          current_version: 4,
        });
      },
    });
    conflicted.schedule({ title: "冲突的本地标题" });
    await new Promise((resolve) => setTimeout(resolve, 0));
    await flushPromises();
    expect(conflicted.state.value).toBe("conflict");

    const changedBase = createAutosave({
      key: "changeset-autosave-base-release-conflict",
      delayMs: 0,
      save: async () => {
        throw new ApiError(409, "BASE_RELEASE_CONFLICT", "base-request", "conflict");
      },
    });
    changedBase.schedule({ title: "基于旧发布版本的标题" });
    await new Promise((resolve) => setTimeout(resolve, 0));
    await flushPromises();
    expect(changedBase.state.value).toBe("error");

    const rejected = createAutosave({
      key: "changeset-autosave-validation-rejected",
      delayMs: 0,
      save: async () => {
        throw new ApiError(422, "VALIDATION_ERROR", "validation-request", "validation");
      },
    });
    rejected.schedule({ title: "服务器拒绝的标题" });
    await new Promise((resolve) => setTimeout(resolve, 0));
    await flushPromises();
    expect(rejected.state.value).toBe("error");

    let releaseSave: (() => void) | undefined;
    let markSaveStarted: (() => void) | undefined;
    const saveStarted = new Promise<void>((resolve) => { markSaveStarted = resolve; });
    const saveBlocked = new Promise<void>((resolve) => { releaseSave = resolve; });
    const disposedSave = vi.fn(async () => {
      markSaveStarted?.();
      await saveBlocked;
    });
    const disposed = createAutosave({
      key: "changeset-autosave-disposed",
      delayMs: 0,
      save: disposedSave,
    });
    disposed.schedule({ title: "first" });
    await saveStarted;
    disposed.schedule({ title: "second" });
    disposed.dispose();
    releaseSave?.();
    await new Promise((resolve) => setTimeout(resolve, 0));
    await flushPromises();
    expect(disposedSave).toHaveBeenCalledTimes(1);
  });

  it("creates a draft and copies release-pinned Paper and evidence revisions", async () => {
    const requests: Array<{ path: string; method: string; body?: Record<string, unknown>; csrf: string | null }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      const headers = new Headers(init?.headers);
      const body = typeof init?.body === "string"
        ? JSON.parse(init.body) as Record<string, unknown>
        : undefined;
      requests.push({ path, method: init?.method ?? "GET", body, csrf: headers.get("X-CSRF-Token") });
      if (path === "/api/v1/review/tasks") return jsonResponse(200, tasks);
      if (path === "/api/v1/review/changesets" && init?.method !== "POST") return jsonResponse(200, []);
      if (path === `/api/v1/papers/${paperId}`) return jsonResponse(200, {
        request_id: "review-ui-request",
        release: {
          id: releaseId,
          key: "baseline-2026-09-12",
          title: "LeadTrace baseline",
          published_at: "2026-09-12T00:00:00Z",
          verification_status: "unverified",
        },
        paper: {
          id: paperId,
          revision_id: baseRevisionId,
          paper_key: "paper-24",
          doi: "10.1000/paper-24",
          title: "Published optimization study 24",
          year: "2026",
          target: "Kinase A",
          review_status: "unreviewed",
        },
        compounds: [],
        lineages: [],
        lineage_edges: [],
        structures: [],
        evidence: [{
          id: "71000000-0000-4000-8000-000000000001",
          revision_id: "81000000-0000-4000-8000-000000000001",
          state: "confirmed",
          text: "Published evidence excerpt",
        }],
        activities: [],
        quality_summary: {
          relations: { resolved: 0, total: 0 },
          structures: { confirmed: 0, total: 0 },
          pair_ready: { eligible: 0, total: 0 },
          human_review: { reviewed: 0, total: 2 },
        },
      });
      if (path === "/api/v1/review/changesets" && init?.method === "POST") {
        return jsonResponse(201, { ...draft, id: changesetId, review_task_id: openTaskId, paper_id: paperId, version: 1 });
      }
      if (path === `/api/v1/review/changesets/${changesetId}/items/from-base`) {
        const version = Number(body?.expected_version) + 1;
        return jsonResponse(201, { ...item, changeset_version: version });
      }
      return jsonResponse(404, {
        code: "RESOURCE_NOT_FOUND",
        message: "Resource not found",
        details: {},
        request_id: "review-ui-request",
      });
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/changesets?task=${openTaskId}`);
    await router.isReady();

    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();
    expect(wrapper.get("h1").text()).toBe("创建核查草稿");
    expect(wrapper.text()).toContain("Published optimization study 24");
    await wrapper.get("#new-changeset-title").setValue("核查 paper-24 的元数据与证据");
    await wrapper.get("#new-changeset-reason").setValue("逐项对照原始文献进行人工核查");
    await wrapper.get("[data-create-changeset]").trigger("submit");
    await flushPromises();

    expect(router.currentRoute.value.path).toBe(`/review/changesets/${changesetId}`);
    const createRequest = requests.find((request) => (
      request.path === "/api/v1/review/changesets" && request.method === "POST"
    ));
    expect(createRequest?.body).toMatchObject({
      review_task_id: openTaskId,
      paper_id: paperId,
      base_release_id: releaseId,
      initialize_from_base: true,
    });
    expect(createRequest?.csrf).toBe("reviewer-csrf");
    const copiedItems = requests.filter((request) => request.path.endsWith("/items/from-base"));
    expect(copiedItems).toHaveLength(0);
  });
});

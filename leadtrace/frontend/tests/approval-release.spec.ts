import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";

import App from "../src/App.vue";
import { createAppRouter } from "../src/app/router";
import { useAuthStore } from "../src/auth/store";

const changesetId = "60000000-0000-4000-8000-000000000021";
const submittedSnapshotHash = "a".repeat(64);
const submittedChangeset = {
  id: changesetId,
  review_task_id: "50000000-0000-4000-8000-000000000021",
  paper_id: "20000000-0000-4000-8000-000000000021",
  owner_id: "10000000-0000-4000-8000-000000000021",
  base_release_id: "30000000-0000-4000-8000-000000000021",
  title: "核对 JMC 文献结构关系",
  reason: "完成结构和证据核查",
  workflow_state: "submitted",
  version: 4,
  validation_results: {},
  submitted_snapshot: {},
  submitted_content_hash: submittedSnapshotHash,
  submitted_at: "2026-09-12T02:00:00Z",
  created_at: "2026-09-12T01:00:00Z",
  updated_at: "2026-09-12T02:00:00Z",
};
const approvedChangeset = { ...submittedChangeset, workflow_state: "approved" };
const releaseId = "30000000-0000-4000-8000-000000000099";

function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
} {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function scientificEvidence(
  targetChangesetId: string,
  smiles = "CCN",
  submissionVersion = submittedChangeset.version,
  snapshotHash = submittedSnapshotHash,
) {
  return {
    changeset_id: targetChangesetId,
    base_release_id: submittedChangeset.base_release_id,
    submission_version: submissionVersion,
    snapshot_hash: snapshotHash,
    structures: [{
      object_id: "61000000-0000-4000-8000-000000000021",
      before: { canonical_smiles: "CCO" },
      after: { canonical_smiles: smiles },
    }],
    regions: [],
  };
}

function changesetDiff(value: string) {
  return [{
    object_id: "61000000-0000-4000-8000-000000000021",
    object_kind: "structure",
    base_revision_id: "70000000-0000-4000-8000-000000000021",
    proposed_revision_id: "71000000-0000-4000-8000-000000000021",
    change_type: "update",
    changes: [{
      path: "/canonical_smiles",
      category: "smiles",
      before_present: true,
      after_present: true,
      before: "CCO",
      after: value,
    }],
  }];
}

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "X-Request-ID": "approval-ui" },
  });
}

function apiFailure(status: 409 | 422, requestId: string): Response {
  return response({
    code: status === 409 ? "RELEASE_CONFLICT" : "RELEASE_VALIDATION_FAILED",
    message: status === 409 ? "Release changed" : "Release validation failed",
    details: {},
    request_id: requestId,
  }, status);
}

describe("approval and release console", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    useAuthStore().acceptSession({
      user: { username: "admin", display_name: "管理员", role: "admin", must_change_password: false },
      csrf_token: "csrf",
    });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/approvals") return response([]);
      if (path === "/api/v1/releases") return response([]);
      return response({});
    }));
  });

  afterEach(() => vi.unstubAllGlobals());

  it("renders the approval center with review actions", async () => {
    const router = createAppRouter(createMemoryHistory());
    await router.push("/admin/approvals");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();
    expect(wrapper.get("h1").text()).toBe("审批中心");
    expect(wrapper.text()).toContain("请求修改");
    expect(wrapper.text()).toContain("批准");
  });

  it("links a pending approval to the complete review workspace", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/review/changesets") return response([submittedChangeset]);
      if (path === `/api/v1/review/changesets/${changesetId}/diff`) return response([]);
      if (path === "/api/v1/approvals") return response([]);
      return response({});
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/admin/approvals");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    const link = wrapper.get("[data-review-workspace-link]");
    expect(link.attributes("href")).toBe(`/review/changesets/${changesetId}`);
  });

  it("shows structure, PDF Region, visual binding, and lineage review before approval", async () => {
    const requestedPaths: string[] = [];
    const structureId = "61000000-0000-4000-8000-000000000021";
    const regionId = "62000000-0000-4000-8000-000000000021";
    const objectId = "63000000-0000-4000-8000-000000000021";
    const compoundId = "64000000-0000-4000-8000-000000000021";
    const assetId = "65000000-0000-4000-8000-000000000021";
    const lineageId = "66000000-0000-4000-8000-000000000021";
    const edgeId = "67000000-0000-4000-8000-000000000021";
    const scientificChangeset = {
      ...submittedChangeset,
      submitted_snapshot: {
        items: [
          {
            id: "68000000-0000-4000-8000-000000000021",
            object_id: structureId,
            object_kind: "structure",
            proposed_snapshot: {
              canonical_smiles: "CCN",
              structure_state: "structure_confirmed",
              drawing_asset_id: assetId,
            },
          },
          {
            id: "68000000-0000-4000-8000-000000000023",
            object_id: edgeId,
            object_kind: "lineage_edge",
            proposed_snapshot: {
              lineage_id: lineageId,
              parent_compound_id: compoundId,
              derived_compound_id: "64000000-0000-4000-8000-000000000022",
              relation_type: "direct_analogue",
              relation_status: "human_confirmed",
            },
          },
        ],
        binding_delta: {
          visual_object_regions: [{ id: "69000000-0000-4000-8000-000000000021", visual_object_id: objectId, region_id: regionId, role: "source", operation: "add" }],
          visual_object_assets: [{ id: "69000000-0000-4000-8000-000000000022", visual_object_id: objectId, asset_id: assetId, role: "image", is_primary: true, operation: "update" }],
          visual_object_compounds: [{ id: "69000000-0000-4000-8000-000000000023", visual_object_id: objectId, compound_id: compoundId, label: "7a", role: "label", is_primary: true, operation: "remove" }],
          visual_object_relations: [{ id: "69000000-0000-4000-8000-000000000024", source_object_id: objectId, target_object_id: "63000000-0000-4000-8000-000000000022", relation_type: "substituent_of", operation: "remove" }],
        },
      },
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      requestedPaths.push(path);
      if (path === "/api/v1/review/changesets") return response([scientificChangeset]);
      if (path === `/api/v1/approvals/${changesetId}/scientific-evidence`) {
        return response({
          changeset_id: changesetId,
          base_release_id: scientificChangeset.base_release_id,
          submission_version: scientificChangeset.version,
          snapshot_hash: scientificChangeset.submitted_content_hash,
          structures: [{
            object_id: structureId,
            before: {
              canonical_smiles: "CCO",
              structure_state: "structure_confirmed",
              drawing_asset_id: assetId,
            },
            after: {
              canonical_smiles: "CCN",
              structure_state: "structure_confirmed",
              drawing_asset_id: assetId,
            },
          }],
          regions: [{
            object_id: regionId,
            before: {
              region_key: "Fig. 2 / 7a",
              page_number: 2,
              bounds: { x0: 0.15, y0: 0.2, x1: 0.7, y1: 0.8 },
              rotation: 0,
            },
            after: {
              region_key: "Fig. 2 / 7a",
              page_number: 2,
              bounds: { x0: 0.1, y0: 0.2, x1: 0.7, y1: 0.8 },
              rotation: 0,
            },
          }],
        });
      }
      if (path === `/api/v1/review/changesets/${changesetId}/diff`) {
        return response([
          {
            object_id: structureId,
            object_kind: "structure",
            base_revision_id: "70000000-0000-4000-8000-000000000021",
            proposed_revision_id: "71000000-0000-4000-8000-000000000021",
            change_type: "update",
            changes: [
              { path: "/review_status", category: "status", before_present: true, after_present: true, before: "pending", after: "reviewed" },
            ],
          },
          {
            object_id: regionId,
            object_kind: "visual_region",
            base_revision_id: "70000000-0000-4000-8000-000000000022",
            proposed_revision_id: "71000000-0000-4000-8000-000000000022",
            change_type: "update",
            changes: [
              { path: "/bounds/x0", category: "region_coordinate", before_present: true, after_present: true, before: 0.15, after: 0.1 },
            ],
          },
          {
            object_id: edgeId,
            object_kind: "lineage_edge",
            base_revision_id: "70000000-0000-4000-8000-000000000023",
            proposed_revision_id: "71000000-0000-4000-8000-000000000023",
            change_type: "update",
            changes: [
              { path: "/parent_compound_id", category: "lineage_endpoint", before_present: true, after_present: true, before: "64000000-0000-4000-8000-000000000020", after: compoundId },
            ],
          },
        ]);
      }
      if (path === "/api/v1/approvals") return response([]);
      return response({});
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/admin/approvals");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.get("[data-scientific-approval]").text()).toContain("科学核查");
    expect(wrapper.find("[data-structure-comparison]").exists()).toBe(true);
    expect(wrapper.find("[data-pdf-page]").exists()).toBe(true);
    expect(wrapper.find("[data-binding-review]").exists()).toBe(true);
    expect(wrapper.find("[data-lineage-comparison]").exists()).toBe(true);
    expect(wrapper.get("[data-structure-comparison]").text()).toContain("CCO");
    const operations = wrapper.findAll("[data-binding-operation]").map((entry) => entry.text());
    expect(operations).toEqual(expect.arrayContaining(["新增", "修改", "删除"]));
    expect(operations).toHaveLength(4);
    expect(wrapper.findAll(".is-remove")).toHaveLength(2);
    expect(requestedPaths).toContain(`/api/v1/approvals/${changesetId}/scientific-evidence`);
    expect(requestedPaths).not.toContain(`/api/v1/papers/${scientificChangeset.paper_id}/regions`);
  });

  it("ignores stale diff and evidence responses after selecting another changeset", async () => {
    const nextChangesetId = "60000000-0000-4000-8000-000000000022";
    const nextChangeset = {
      ...submittedChangeset,
      id: nextChangesetId,
      title: "第二个待审批修改集",
    };
    const oldDiff = deferred<Response>();
    const oldEvidence = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/review/changesets") return response([submittedChangeset, nextChangeset]);
      if (path === "/api/v1/approvals") return response([]);
      if (path === `/api/v1/review/changesets/${changesetId}/diff`) return oldDiff.promise;
      if (path === `/api/v1/approvals/${changesetId}/scientific-evidence`) return oldEvidence.promise;
      if (path === `/api/v1/review/changesets/${nextChangesetId}/diff`) return response(changesetDiff("NEW_DIFF"));
      if (path === `/api/v1/approvals/${nextChangesetId}/scientific-evidence`) return response(scientificEvidence(nextChangesetId, "NEW_EVIDENCE"));
      return response({});
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/admin/approvals");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();
    await wrapper.findAll(".queue-item")[1].trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("NEW_DIFF");
    expect(wrapper.text()).toContain("NEW_EVIDENCE");
    oldDiff.resolve(response(changesetDiff("OLD_DIFF")));
    oldEvidence.resolve(response(scientificEvidence(changesetId, "OLD_EVIDENCE")));
    await flushPromises();

    expect(wrapper.text()).toContain("NEW_DIFF");
    expect(wrapper.text()).toContain("NEW_EVIDENCE");
    expect(wrapper.text()).not.toContain("OLD_DIFF");
    expect(wrapper.text()).not.toContain("OLD_EVIDENCE");
  });

  it("reloads review data when the selected changeset has a new submission version", async () => {
    const refreshedChangeset = {
      ...submittedChangeset,
      version: 6,
      submitted_content_hash: "b".repeat(64),
      updated_at: "2026-09-12T04:00:00Z",
    };
    const refreshedDiff = deferred<Response>();
    const refreshedEvidence = deferred<Response>();
    let changesetLoads = 0;
    let diffLoads = 0;
    let evidenceLoads = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/review/changesets") {
        changesetLoads += 1;
        return response([changesetLoads === 1 ? submittedChangeset : refreshedChangeset]);
      }
      if (path === "/api/v1/approvals") return response([]);
      if (path === `/api/v1/review/changesets/${changesetId}/diff`) {
        diffLoads += 1;
        return diffLoads === 1
          ? response(changesetDiff("OLD_SUBMISSION_DIFF"))
          : refreshedDiff.promise;
      }
      if (path === `/api/v1/approvals/${changesetId}/scientific-evidence`) {
        evidenceLoads += 1;
        return evidenceLoads === 1
          ? response(scientificEvidence(changesetId, "OLD_SUBMISSION_EVIDENCE"))
          : refreshedEvidence.promise;
      }
      return response({});
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/admin/approvals");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();
    await wrapper.get("#decision-reason").setValue("核对新提交版本");
    const actions = () => wrapper.findAll(".decision-actions button");

    expect(wrapper.text()).toContain("OLD_SUBMISSION_DIFF");
    expect(wrapper.text()).toContain("OLD_SUBMISSION_EVIDENCE");
    expect(actions().every((button) => button.attributes("disabled") === undefined)).toBe(true);

    await wrapper.get(".queue-heading button").trigger("click");
    await flushPromises();

    expect(wrapper.get(".summary-band").text()).toContain("v6");
    expect(wrapper.text()).not.toContain("OLD_SUBMISSION_DIFF");
    expect(wrapper.text()).not.toContain("OLD_SUBMISSION_EVIDENCE");
    expect(wrapper.get("[data-diff-status]").text()).toContain("正在读取");
    expect(wrapper.get("[data-evidence-status]").text()).toContain("正在读取");
    expect(actions().every((button) => button.attributes("disabled") !== undefined)).toBe(true);

    refreshedDiff.resolve(response(changesetDiff("NEW_SUBMISSION_DIFF")));
    await flushPromises();
    expect(actions().every((button) => button.attributes("disabled") !== undefined)).toBe(true);

    refreshedEvidence.resolve(response(scientificEvidence(
      changesetId,
      "NEW_SUBMISSION_EVIDENCE",
      refreshedChangeset.version,
      refreshedChangeset.submitted_content_hash,
    )));
    await flushPromises();

    expect(wrapper.text()).toContain("NEW_SUBMISSION_DIFF");
    expect(wrapper.text()).toContain("NEW_SUBMISSION_EVIDENCE");
    expect(actions().every((button) => button.attributes("disabled") === undefined)).toBe(true);
  });

  it("rejects scientific evidence from a different submission version", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/review/changesets") return response([submittedChangeset]);
      if (path === "/api/v1/approvals") return response([]);
      if (path === `/api/v1/review/changesets/${changesetId}/diff`) return response([]);
      if (path === `/api/v1/approvals/${changesetId}/scientific-evidence`) {
        return response(scientificEvidence(
          changesetId,
          "STALE_SUBMISSION_EVIDENCE",
          submittedChangeset.version - 1,
          "c".repeat(64),
        ));
      }
      return response({});
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/admin/approvals");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();
    await wrapper.get("#decision-reason").setValue("不得使用旧提交证据");

    expect(wrapper.get("[data-evidence-status]").text()).toContain("证据未能读取");
    expect(wrapper.text()).not.toContain("STALE_SUBMISSION_EVIDENCE");
    expect(wrapper.findAll(".decision-actions button").every(
      (button) => button.attributes("disabled") !== undefined,
    )).toBe(true);
  });

  it("shows evidence failures and keeps every decision action disabled", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/review/changesets") return response([submittedChangeset]);
      if (path === "/api/v1/approvals") return response([]);
      if (path === `/api/v1/review/changesets/${changesetId}/diff`) return response([]);
      if (path === `/api/v1/approvals/${changesetId}/scientific-evidence`) return response({}, 500);
      return response({});
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/admin/approvals");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();
    await wrapper.get("#decision-reason").setValue("证据读取失败时不可审批");

    expect(wrapper.get("[data-evidence-status]").text()).toContain("证据未能读取");
    expect(wrapper.findAll(".decision-actions button").every((button) => button.attributes("disabled") !== undefined)).toBe(true);
  });

  it("enables decisions only after the current diff and evidence are both ready", async () => {
    const pendingDiff = deferred<Response>();
    const pendingEvidence = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/review/changesets") return response([submittedChangeset]);
      if (path === "/api/v1/approvals") return response([]);
      if (path === `/api/v1/review/changesets/${changesetId}/diff`) return pendingDiff.promise;
      if (path === `/api/v1/approvals/${changesetId}/scientific-evidence`) return pendingEvidence.promise;
      return response({});
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/admin/approvals");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();
    await wrapper.get("#decision-reason").setValue("完整核对后批准");
    const actions = () => wrapper.findAll(".decision-actions button");

    expect(actions().every((button) => button.attributes("disabled") !== undefined)).toBe(true);
    pendingDiff.resolve(response([]));
    await flushPromises();
    expect(actions().every((button) => button.attributes("disabled") !== undefined)).toBe(true);
    pendingEvidence.resolve(response(scientificEvidence(changesetId)));
    await flushPromises();
    expect(actions().every((button) => button.attributes("disabled") === undefined)).toBe(true);
  });

  it("shows approval history only for the selected changeset", async () => {
    const decision = (id: string, targetId: string, reason: string) => ({
      id,
      changeset_id: targetId,
      submission_version: 4,
      decision: "approve",
      actor_id: "10000000-0000-4000-8000-000000000099",
      reason,
      snapshot: {},
      snapshot_hash: "a".repeat(64),
      created_at: "2026-09-12T03:00:00Z",
    });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/review/changesets") return response([submittedChangeset]);
      if (path === `/api/v1/review/changesets/${changesetId}/diff`) return response([]);
      if (path === "/api/v1/approvals") {
        return response([
          decision("70000000-0000-4000-8000-000000000021", changesetId, "当前修改集决定"),
          decision(
            "70000000-0000-4000-8000-000000000022",
            "60000000-0000-4000-8000-000000000022",
            "其他修改集决定",
          ),
        ]);
      }
      return response({});
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/admin/approvals");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.get(".history-panel").text()).toContain("当前修改集决定");
    expect(wrapper.get(".history-panel").text()).not.toContain("其他修改集决定");
  });

  it("renders releases and exposes rollback navigation", async () => {
    const router = createAppRouter(createMemoryHistory());
    await router.push("/admin/releases");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();
    expect(wrapper.get("h1").text()).toBe("发布管理");
    expect(wrapper.text()).toContain("回滚");
  });

  it("previews the release delta before publishing with protected request headers", async () => {
    const calls: Array<{ path: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      calls.push({ path, init });
      if (path === "/api/v1/releases") return response([]);
      if (path === "/api/v1/review/changesets") return response([approvedChangeset]);
      if (path === `/api/v1/releases/preview/${changesetId}`) {
        return response({
          changeset_id: changesetId,
          base_release_id: approvedChangeset.base_release_id,
          counts: { create: 2, update: 1, tombstone: 1, total: 4 },
          by_object_kind: { compound: { create: 2, update: 0, tombstone: 1, total: 3 } },
          objects: [],
          affected_asset_ids: ["80000000-0000-4000-8000-000000000021"],
          validation: { valid: true, issues: [], asset_ids: [] },
        });
      }
      if (path === "/api/v1/releases/publish") {
        return response({
          release_id: releaseId,
          release_key: "release-20260912",
          validation: { valid: true },
          idempotent: false,
          operation_id: "90000000-0000-4000-8000-000000000021",
        });
      }
      return response({});
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/admin/releases");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.get("[data-release-preview]").text()).toContain("2");
    expect(wrapper.get("[data-release-preview]").text()).toContain("校验通过");
    await wrapper.get("[data-publish-release]").trigger("click");
    await flushPromises();

    const request = calls.find((call) => call.path === "/api/v1/releases/publish");
    expect(request).toBeTruthy();
    expect(new Headers(request?.init?.headers).get("X-CSRF-Token")).toBe("csrf");
    expect(new Headers(request?.init?.headers).get("Idempotency-Key")).toBeTruthy();
    expect(JSON.parse(String(request?.init?.body))).toEqual({
      changeset_id: changesetId,
      notes: "",
    });
  });

  it("sends rollback with CSRF, idempotency key, and the selected reason", async () => {
    const requests: RequestInit[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === "/api/v1/releases") {
        return response([{ id: releaseId, release_key: "release-old", title: "旧版本", notes: "", published_at: "2026-09-11T00:00:00Z", is_current: false, manifest_finalized: true, metrics: {} }]);
      }
      if (path === "/api/v1/releases/rollback") {
        requests.push(init ?? {});
        return response({ release_id: releaseId, release_key: "rollback-old", validation: { valid: true }, idempotent: false, operation_id: "90000000-0000-4000-8000-000000000022" });
      }
      return response({});
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/admin/releases/rollback");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();
    await wrapper.get("#rollback-target").setValue(releaseId);
    await wrapper.get("#rollback-reason").setValue("恢复经过复核的稳定版本");
    await wrapper.get(".button-danger").trigger("click");
    await flushPromises();

    expect(requests).toHaveLength(1);
    expect(new Headers(requests[0].headers).get("X-CSRF-Token")).toBe("csrf");
    expect(new Headers(requests[0].headers).get("Idempotency-Key")).toBeTruthy();
    expect(JSON.parse(String(requests[0].body))).toEqual({
      target_release_id: releaseId,
      reason: "恢复经过复核的稳定版本",
    });
  });

  it.each([
    [409, "发布候选已经发生变化，请重新核对后再次发布。", "publish-409"],
    [422, "发布校验未通过，当前版本保持不变。", "publish-422"],
  ] as const)(
    "distinguishes publish HTTP %i failures and shows the request id",
    async (status, message, requestId) => {
      vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
        const path = new URL(String(input), "http://leadtrace.test").pathname;
        if (path === "/api/v1/releases") return response([]);
        if (path === "/api/v1/review/changesets") return response([approvedChangeset]);
        if (path === `/api/v1/releases/preview/${changesetId}`) {
          return response({
            changeset_id: changesetId,
            base_release_id: approvedChangeset.base_release_id,
            counts: { create: 0, update: 1, tombstone: 0, total: 1 },
            by_object_kind: {
              paper: { create: 0, update: 1, tombstone: 0, total: 1 },
            },
            objects: [],
            affected_asset_ids: [],
            validation: { valid: true, issues: [] },
          });
        }
        if (path === "/api/v1/releases/publish") {
          return apiFailure(status, requestId);
        }
        return response({});
      }));
      const router = createAppRouter(createMemoryHistory());
      await router.push("/admin/releases");
      await router.isReady();
      const wrapper = mount(App, { global: { plugins: [router] } });
      await flushPromises();

      await wrapper.get("[data-publish-release]").trigger("click");
      await flushPromises();

      expect(wrapper.get('[role="alert"]').text()).toContain(message);
      expect(wrapper.get('[role="alert"]').text()).toContain(requestId);
    },
  );

  it.each([
    [409, "当前发布版本已经变化，请重新选择回滚目标。", "rollback-409"],
    [422, "回滚目标未通过完整性校验，当前版本保持不变。", "rollback-422"],
  ] as const)(
    "distinguishes rollback HTTP %i failures and shows the request id",
    async (status, message, requestId) => {
      vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
        const path = new URL(String(input), "http://leadtrace.test").pathname;
        if (path === "/api/v1/releases") {
          return response([{ id: releaseId, release_key: "release-old", title: "旧版本", notes: "", published_at: "2026-09-11T00:00:00Z", is_current: false, manifest_finalized: true, metrics: {} }]);
        }
        if (path === "/api/v1/releases/rollback") {
          return apiFailure(status, requestId);
        }
        return response({});
      }));
      const router = createAppRouter(createMemoryHistory());
      await router.push("/admin/releases/rollback");
      await router.isReady();
      const wrapper = mount(App, { global: { plugins: [router] } });
      await flushPromises();
      await wrapper.get("#rollback-target").setValue(releaseId);
      await wrapper.get("#rollback-reason").setValue("恢复稳定版本");

      await wrapper.get(".button-danger").trigger("click");
      await flushPromises();

      expect(wrapper.get('[role="alert"]').text()).toContain(message);
      expect(wrapper.get('[role="alert"]').text()).toContain(requestId);
    },
  );
});

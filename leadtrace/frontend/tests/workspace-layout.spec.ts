import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";

import PdfReviewCanvas from "../src/pdf-viewer/PdfReviewCanvas.vue";
import { useAuthStore } from "../src/auth/store";
import PaperWorkspace from "../src/review/workspace/PaperWorkspace.vue";

const ids = {
  changeset: "10000000-0000-4000-8000-000000000001",
  task: "10000000-0000-4000-8000-000000000002",
  paper: "10000000-0000-4000-8000-000000000003",
  owner: "10000000-0000-4000-8000-000000000004",
  release: "10000000-0000-4000-8000-000000000005",
  firstRegion: "10000000-0000-4000-8000-000000000006",
  firstVisual: "10000000-0000-4000-8000-000000000007",
  firstProposal: "10000000-0000-4000-8000-000000000008",
  revision: "10000000-0000-4000-8000-000000000009",
  crop: "10000000-0000-4000-8000-000000000010",
  structure: "10000000-0000-4000-8000-000000000011",
  compound: "10000000-0000-4000-8000-000000000012",
  scope: "10000000-0000-4000-8000-000000000013",
  drawing: "10000000-0000-4000-8000-000000000014",
  secondRegion: "10000000-0000-4000-8000-000000000015",
  secondVisual: "10000000-0000-4000-8000-000000000016",
  secondProposal: "10000000-0000-4000-8000-000000000017",
};

function asset(id: string, category: "ocsr_input" | "rdkit_structure") {
  return {
    id,
    url: `/api/v1/assets/${id}/content`,
    original_filename: category === "ocsr_input" ? "molecule.png" : "structure.svg",
    sha256: category === "ocsr_input" ? "a".repeat(64) : "c".repeat(64),
    byte_size: 2048,
    mime_type: category === "ocsr_input" ? "image/png" : "image/svg+xml",
    width: 320,
    height: 180,
    page_count: null,
    category,
    access_level: "reviewer",
  };
}

const cropAsset = asset(ids.crop, "ocsr_input");
const drawingAsset = asset(ids.drawing, "rdkit_structure");
const firstBounds = { x0: 0.1, y0: 0.2, x1: 0.4, y1: 0.6 };
const secondBounds = { x0: 0.5, y0: 0.25, x1: 0.8, y1: 0.7 };

const workspace = {
  workspace_version: 3,
  changeset: {
    id: ids.changeset,
    review_task_id: ids.task,
    paper_id: ids.paper,
    owner_id: ids.owner,
    base_release_id: ids.release,
    workflow_state: "draft",
    version: 3,
    title: "Review Paper",
    reason: "Verify source evidence",
  },
  paper: {
    id: ids.paper,
    paper_key: "paper-1",
    title: "Example kinase optimization Paper",
    base_release_id: ids.release,
  },
  progress: {
    scope_count: 7,
    resolved_count: 5,
    blocker_count: 2,
    by_kind: {
      visual_region: { total: 2, resolved: 2, blockers: 0 },
      visual_object: { total: 2, resolved: 2, blockers: 0 },
      molecule_proposal: { total: 2, resolved: 0, blockers: 2 },
      structure: { total: 1, resolved: 1, blockers: 0 },
    },
  },
  document: {
    url: `/api/v1/papers/${ids.paper}/source-pdf?kind=article&release_id=${ids.release}`,
    release_id: ids.release,
  },
  pages: [
    { page_number: 1, region_count: 1, visual_object_count: 1, proposal_count: 1, blocker_count: 1 },
    { page_number: 2, region_count: 1, visual_object_count: 1, proposal_count: 1, blocker_count: 1 },
  ],
  regions: [
    {
      id: ids.firstRegion,
      region_key: "region-1",
      revision_id: ids.revision,
      page_number: 1,
      bounds: firstBounds,
      rotation: 0,
      asset_id: null,
      asset: null,
      is_tombstone: false,
    },
    {
      id: ids.secondRegion,
      region_key: "region-2",
      revision_id: ids.revision,
      page_number: 2,
      bounds: secondBounds,
      rotation: 0,
      asset_id: null,
      asset: null,
      is_tombstone: false,
    },
  ],
  visual_objects: [
    {
      id: ids.firstVisual,
      object_key: "object-1",
      object_type: "complete_molecule",
      revision_id: ids.revision,
      snapshot: { display_label: "Lead compound" },
      queue_state: "proposal_review",
      blocking: true,
      region_id: ids.firstRegion,
      bindings: { regions: [], assets: [], compounds: [], relations: [] },
    },
    {
      id: ids.secondVisual,
      object_key: "object-2",
      object_type: "complete_molecule",
      revision_id: ids.revision,
      snapshot: { display_label: "Follow-up compound" },
      queue_state: "needs_ocsr",
      blocking: true,
      region_id: ids.secondRegion,
      bindings: { regions: [], assets: [], compounds: [], relations: [] },
    },
  ],
  molecule_proposals: [
    {
      id: ids.firstProposal,
      paper_id: ids.paper,
      visual_object_id: ids.firstVisual,
      proposal_key: "proposal-1",
      model_run_key: "ocsr-v1",
      revision_id: ids.revision,
      disposition: "pending",
      machine: {
        raw_values: { raw_smiles: "CCO" },
        normalized_values: { canonical_smiles: "CCO", min_token_confidence: 0.42 },
      },
      review: { resulting_structure_id: ids.structure },
      crop_asset: cropAsset,
      source_region_id: ids.firstRegion,
    },
    {
      id: ids.secondProposal,
      paper_id: ids.paper,
      visual_object_id: ids.secondVisual,
      proposal_key: "proposal-2",
      model_run_key: "ocsr-v1",
      revision_id: ids.revision,
      disposition: "pending",
      machine: { raw_values: {}, normalized_values: {} },
      review: {},
      crop_asset: null,
      source_region_id: ids.secondRegion,
    },
  ],
  structures: [{
    id: ids.structure,
    compound_id: ids.compound,
    structure_key: "structure-1",
    revision_id: ids.revision,
    state: "structure_confirmed",
    canonical_smiles: "CCO",
    snapshot: { drawing_asset_id: ids.drawing },
  }],
  evidence: [],
  assets: [cropAsset, drawingAsset],
  source_locators: [
    {
      visual_object_id: ids.firstVisual,
      region_id: ids.firstRegion,
      page_number: 1,
      bounds: firstBounds,
      source_asset_id: null,
      crop_asset_id: ids.crop,
    },
    {
      visual_object_id: ids.secondVisual,
      region_id: ids.secondRegion,
      page_number: 2,
      bounds: secondBounds,
      source_asset_id: null,
      crop_asset_id: null,
    },
  ],
  attestation: null,
  scope: { id: ids.scope, scope_hash: "b".repeat(64), item_count: 7 },
};

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function errorResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "X-Request-ID": "workspace-request" },
  });
}

async function mountWorkspace(query = "") {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/review/changesets/:changesetId", component: { template: "<div />" } }],
  });
  await router.push(`/review/changesets/${ids.changeset}${query}`);
  await router.isReady();
  const wrapper = mount(PaperWorkspace, {
    props: { changesetId: ids.changeset, saveState: "saved" },
    global: { plugins: [router] },
  });
  await flushPromises();
  return { wrapper, router };
}

describe("Paper scientific workspace layout", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    useAuthStore().acceptSession({
      user: {
        username: "reviewer.one",
        display_name: "Reviewer One",
        role: "reviewer",
        must_change_password: false,
      },
      csrf_token: "reviewer-csrf",
    });
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(workspace)));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("opens an exact deep link in the three-pane shell", async () => {
    const { wrapper } = await mountWorkspace(
      `?view=ocsr&page=1&object=${ids.firstVisual}&proposal=${ids.firstProposal}`,
    );

    expect(wrapper.get("[data-paper-workspace]").classes()).toContain("paper-workspace-shell");
    expect(wrapper.get("[data-context-rail]").classes()).toContain("workspace-context-rail");
    expect(wrapper.get("[data-evidence-canvas]").classes()).toContain("workspace-evidence-canvas");
    expect(wrapper.get("[data-workspace-inspector]").classes()).toContain("workspace-inspector");
    expect(wrapper.get("[data-workspace-action-bar]").classes()).toContain("workspace-action-bar");
    expect(wrapper.get(`[data-visual-object-id='${ids.firstVisual}']`).attributes("aria-current")).toBe("true");
    expect(wrapper.get("[data-selected-proposal]").text()).toContain("proposal-1");
    expect(wrapper.get("[data-selected-region]").text()).toContain("region-1");
    expect(wrapper.get("[data-workspace-tabs] [aria-current='page']").text()).toContain("OCSR");
    expect(wrapper.text()).not.toContain("对象已核验");
  });

  it("moves to adjacent unresolved objects and updates the URL without a reload", async () => {
    const { wrapper, router } = await mountWorkspace(
      `?view=ocsr&page=1&object=${ids.firstVisual}&proposal=${ids.firstProposal}`,
    );
    const fetchMock = vi.mocked(fetch);
    const readsBeforeNavigation = fetchMock.mock.calls.length;

    await wrapper.get("[data-next-unresolved]").trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.query.object).toBe(ids.secondVisual);
    expect(router.currentRoute.value.query.proposal).toBe(ids.secondProposal);
    expect(router.currentRoute.value.query.region).toBe(ids.secondRegion);
    expect(router.currentRoute.value.query.page).toBe("2");
    expect(wrapper.get(`[data-visual-object-id='${ids.secondVisual}']`).attributes("aria-current")).toBe("true");
    expect(fetchMock.mock.calls).toHaveLength(readsBeforeNavigation);

    await wrapper.get("[data-previous-unresolved]").trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.query.object).toBe(ids.firstVisual);
  });

  it("keeps crop and RDKit evidence stable and explains missing evidence", async () => {
    const { wrapper } = await mountWorkspace(
      `?view=ocsr&page=1&object=${ids.firstVisual}&proposal=${ids.firstProposal}`,
    );

    expect(wrapper.get("[data-crop-frame]").classes()).toContain("evidence-preview-frame");
    expect(wrapper.get("[data-rdkit-frame]").classes()).toContain("evidence-preview-frame");
    expect(wrapper.get("[data-crop-frame] img").attributes("src")).toBe(cropAsset.url);
    expect(wrapper.get("[data-rdkit-frame] img").attributes("src")).toBe(drawingAsset.url);
    expect(wrapper.get("[data-rdkit-frame]").text()).toContain("CCO");

    await wrapper.get("[data-evidence-mode='crop']").trigger("click");
    expect(wrapper.get("[data-focused-crop]").attributes("src")).toBe(cropAsset.url);
    await wrapper.get("[data-evidence-mode='page']").trigger("click");
    expect(wrapper.findComponent(PdfReviewCanvas).props("selectedRegionId")).toBe(ids.firstRegion);
    expect(wrapper.findComponent(PdfReviewCanvas).props("page")).toBe(1);
    expect(wrapper.findComponent(PdfReviewCanvas).find(".pdf-fallback").exists()).toBe(true);

    await wrapper.get("[data-next-unresolved]").trigger("click");
    await flushPromises();
    await wrapper.get("[data-evidence-mode='crop']").trigger("click");
    expect(wrapper.get("[data-crop-missing]").text()).toContain("没有可用的 crop");
    expect(wrapper.get("[data-rdkit-missing]").text()).toContain("没有可用的 RDKit 图");
  });

  it("makes precision Region interaction read-only on mobile", async () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({
      matches: true,
      media: "(max-width: 760px)",
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
    const { wrapper } = await mountWorkspace(
      `?view=pdf&page=1&region=${ids.firstRegion}`,
    );

    expect(wrapper.get("[data-desktop-required]").text()).toContain("桌面端");
    expect(wrapper.findComponent(PdfReviewCanvas).props("readOnly")).toBe(true);
  });

  it("saves typed Region bounds and refreshes the version-consistent projection", async () => {
    const calls: Array<{ path: string; method?: string; body?: Record<string, unknown> }> = [];
    let workspaceReads = 0;
    const updatedWorkspace = {
      ...workspace,
      workspace_version: 4,
      changeset: { ...workspace.changeset, version: 4 },
      regions: workspace.regions.map((region) => region.id === ids.firstRegion
        ? { ...region, bounds: { ...region.bounds, x1: 0.5 } }
        : region),
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      calls.push({
        path,
        method: init?.method,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      });
      if (path.endsWith("/workspace")) {
        workspaceReads += 1;
        return jsonResponse(workspaceReads === 1 ? workspace : updatedWorkspace);
      }
      if (path.endsWith(`/regions/${ids.firstRegion}`) && init?.method === "PATCH") {
        return jsonResponse({ revision_id: ids.revision, revision_number: 2 });
      }
      return errorResponse(404, { code: "RESOURCE_NOT_FOUND", message: "missing", details: {}, request_id: "workspace-request" });
    }));
    const { wrapper } = await mountWorkspace(`?view=pdf&page=1&region=${ids.firstRegion}`);

    await wrapper.get("input[name='x1']").setValue("0.5");
    await wrapper.get("[data-save-region]").trigger("click");
    await flushPromises();

    const patchCall = calls.find((call) => call.method === "PATCH");
    expect(patchCall).toMatchObject({
      path: `/api/v1/papers/${ids.paper}/regions/${ids.firstRegion}`,
      body: {
        changeset_id: ids.changeset,
        expected_version: 3,
        page_number: 1,
        bounds: { x0: 0.1, y0: 0.2, x1: 0.5, y1: 0.6 },
        rotation: 0,
      },
    });
    expect(workspaceReads).toBe(2);
    expect(wrapper.get("input[name='x1']").element).toHaveProperty("value", "0.5");
  });

  it("surfaces a Region version conflict without replaying the mutation", async () => {
    let workspaceReads = 0;
    let patchWrites = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path.endsWith("/workspace")) {
        workspaceReads += 1;
        return jsonResponse(workspace);
      }
      if (path.endsWith(`/regions/${ids.firstRegion}`) && init?.method === "PATCH") {
        patchWrites += 1;
        return errorResponse(409, {
          code: "REVISION_CONFLICT",
          message: "Region changed",
          details: { expected_version: 3, current_version: 4 },
          request_id: "workspace-request",
        });
      }
      return errorResponse(404, { code: "RESOURCE_NOT_FOUND", message: "missing", details: {}, request_id: "workspace-request" });
    }));
    const { wrapper } = await mountWorkspace(`?view=pdf&page=1&region=${ids.firstRegion}`);

    await wrapper.get("[data-save-region]").trigger("click");
    await flushPromises();

    expect(wrapper.get("[data-workspace-conflict]").text()).toContain("版本冲突");
    expect(patchWrites).toBe(1);
    expect(workspaceReads).toBe(1);
    await wrapper.get("[data-refresh-conflict]").trigger("click");
    await flushPromises();
    expect(workspaceReads).toBe(2);
    expect(patchWrites).toBe(1);
  });

  it("saves Visual Object type and label through its typed inspector", async () => {
    const writes: Array<Record<string, unknown>> = [];
    let workspaceReads = 0;
    const updatedWorkspace = {
      ...workspace,
      workspace_version: 4,
      changeset: { ...workspace.changeset, version: 4 },
      visual_objects: workspace.visual_objects.map((visual) => visual.id === ids.firstVisual
        ? { ...visual, object_type: "shared_scaffold", snapshot: { display_label: "Lead compound" } }
        : visual),
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path.endsWith("/workspace")) {
        workspaceReads += 1;
        return jsonResponse(workspaceReads === 1 ? workspace : updatedWorkspace);
      }
      if (path.endsWith(`/visual-objects/${ids.firstVisual}`) && init?.method === "PATCH") {
        writes.push(JSON.parse(String(init.body)));
        return jsonResponse({
          id: ids.firstVisual,
          paper_id: ids.paper,
          object_key: "object-1",
          object_type: "shared_scaffold",
          revision_id: ids.revision,
          revision_number: 2,
          changeset_id: ids.changeset,
          changeset_version: 4,
          snapshot: { object_key: "object-1", object_type: "shared_scaffold", label: "Lead compound" },
          workflow_state: "draft",
        });
      }
      return errorResponse(404, { code: "RESOURCE_NOT_FOUND", message: "missing", details: {}, request_id: "workspace-request" });
    }));
    const { wrapper } = await mountWorkspace(`?view=molecules&page=1&object=${ids.firstVisual}`);

    await wrapper.get("select[data-object-type]").setValue("shared_scaffold");
    await wrapper.get("[data-save-object]").trigger("click");
    await flushPromises();

    expect(writes).toEqual([{
      changeset_id: ids.changeset,
      expected_version: 3,
      object_type: "shared_scaffold",
      label: "Lead compound",
    }]);
    expect(workspaceReads).toBe(2);
    expect(wrapper.get("select[data-object-type]").element).toHaveProperty("value", "shared_scaffold");
  });
});

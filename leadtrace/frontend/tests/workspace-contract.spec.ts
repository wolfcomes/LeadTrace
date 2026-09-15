import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "../src/auth/store";
import {
  attestPaper,
  fetchMoleculeObjectQueue,
  fetchMoleculeProposals,
  fetchWorkspace,
  updateMoleculeProposal,
} from "../src/review/api";
import {
  moleculeObjectQueueSchema,
  moleculeProposalSchema,
  workspaceSchema,
} from "../src/review/workspace/types";
import { useWorkspace } from "../src/review/workspace/useWorkspace";

const ids = {
  changeset: "10000000-0000-4000-8000-000000000001",
  task: "10000000-0000-4000-8000-000000000002",
  paper: "10000000-0000-4000-8000-000000000003",
  owner: "10000000-0000-4000-8000-000000000004",
  release: "10000000-0000-4000-8000-000000000005",
  region: "10000000-0000-4000-8000-000000000006",
  visual: "10000000-0000-4000-8000-000000000007",
  proposal: "10000000-0000-4000-8000-000000000008",
  revision: "10000000-0000-4000-8000-000000000009",
  asset: "10000000-0000-4000-8000-000000000010",
  structure: "10000000-0000-4000-8000-000000000011",
  compound: "10000000-0000-4000-8000-000000000012",
  scope: "10000000-0000-4000-8000-000000000013",
};

const asset = {
  id: ids.asset,
  url: `/api/v1/assets/${ids.asset}/content`,
  original_filename: "object.png",
  sha256: "a".repeat(64),
  byte_size: 2048,
  mime_type: "image/png",
  width: 320,
  height: 180,
  page_count: null,
  category: "ocsr_input",
  access_level: "reviewer",
};

const bounds = { x0: 0.1, y0: 0.2, x1: 0.4, y1: 0.6 };

const proposal = {
  id: ids.proposal,
  paper_id: ids.paper,
  visual_object_id: ids.visual,
  proposal_key: "proposal-1",
  model_run_key: "ocsr-v1",
  revision_id: ids.revision,
  disposition: "pending",
  machine: {
    raw_values: { raw_smiles: "CCO" },
    normalized_values: { canonical_smiles: "CCO", min_token_confidence: 0.42 },
  },
  review: {},
  crop_asset: asset,
  source_region_id: ids.region,
};

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
    title: "Example Paper",
    base_release_id: ids.release,
  },
  progress: {
    scope_count: 3,
    resolved_count: 2,
    blocker_count: 1,
    by_kind: {
      visual_region: { total: 1, resolved: 1, blockers: 0 },
      visual_object: { total: 1, resolved: 1, blockers: 0 },
      molecule_proposal: { total: 1, resolved: 0, blockers: 1 },
    },
  },
  document: {
    url: `/api/v1/papers/${ids.paper}/source-pdf?kind=article&release_id=${ids.release}`,
    release_id: ids.release,
  },
  pages: [{
    page_number: 1,
    region_count: 1,
    visual_object_count: 1,
    proposal_count: 1,
    blocker_count: 1,
  }],
  regions: [{
    id: ids.region,
    region_key: "region-1",
    revision_id: ids.revision,
    page_number: 1,
    bounds,
    rotation: 0,
    asset_id: ids.asset,
    asset,
    is_tombstone: false,
  }],
  visual_objects: [{
    id: ids.visual,
    object_key: "object-1",
    object_type: "complete_molecule",
    revision_id: ids.revision,
    snapshot: {},
    queue_state: "proposal_review",
    blocking: true,
    region_id: ids.region,
    bindings: { regions: [], assets: [], compounds: [], relations: [] },
  }],
  molecule_proposals: [proposal],
  structures: [{
    id: ids.structure,
    compound_id: ids.compound,
    structure_key: "structure-1",
    revision_id: ids.revision,
    state: "structure_confirmed",
    canonical_smiles: "CCO",
    snapshot: {},
  }],
  evidence: [],
  assets: [asset],
  source_locators: [{
    visual_object_id: ids.visual,
    region_id: ids.region,
    page_number: 1,
    bounds,
    source_asset_id: ids.asset,
    crop_asset_id: ids.asset,
  }],
  attestation: null,
  scope: { id: ids.scope, scope_hash: "b".repeat(64), item_count: 3 },
};

const queue = {
  items: [{
    paper_id: ids.paper,
    paper_key: "paper-1",
    base_release_id: ids.release,
    review_task_id: ids.task,
    changeset_id: ids.changeset,
    changeset_version: 3,
    visual_object: {
      id: ids.visual,
      object_key: "object-1",
      object_type: "complete_molecule",
      region_id: ids.region,
    },
    proposal: {
      id: ids.proposal,
      proposal_key: "proposal-1",
      disposition: "pending",
      revision_id: ids.revision,
    },
    crop_asset: asset,
    page: 1,
    state: "proposal_review",
    blocking: true,
    reasons: ["proposal_pending"],
    paper_progress: { scope_count: 3, resolved_count: 2, blocker_count: 1 },
    deep_link: { view: "ocsr", page: 1, object: ids.visual, proposal: ids.proposal },
    priority: 80,
  }],
  next_cursor: null,
  status_counts: {
    localization_or_split: 0,
    needs_ocsr: 0,
    proposal_review: 1,
    source_or_attachment: 0,
    structure_assembly: 0,
    complete: 0,
  },
  pagination: { limit: 20, returned: 1 },
};

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("scientific workspace contracts", () => {
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
  });

  it("parses one coherent workspace and molecule queue", () => {
    expect(workspaceSchema.parse(workspace).workspace_version).toBe(3);
    expect(moleculeObjectQueueSchema.parse(queue).items).toHaveLength(1);
  });

  it("rejects cross-Paper IDs, raw paths, negative progress, dispositions, and bounds", () => {
    expect(workspaceSchema.safeParse({
      ...workspace,
      molecule_proposals: [{
        ...proposal,
        paper_id: "20000000-0000-4000-8000-000000000001",
      }],
    }).success).toBe(false);
    expect(workspaceSchema.safeParse({
      ...workspace,
      molecule_proposals: [{
        ...proposal,
        machine: { ...proposal.machine, raw_values: { crop_path: "/tmp/crop.png" } },
      }],
    }).success).toBe(false);
    expect(workspaceSchema.safeParse({
      ...workspace,
      progress: { ...workspace.progress, blocker_count: -1 },
    }).success).toBe(false);
    expect(moleculeProposalSchema.safeParse({
      ...proposal,
      disposition: "object_verified",
    }).success).toBe(false);
    expect(workspaceSchema.safeParse({
      ...workspace,
      regions: [{ ...workspace.regions[0], bounds: { ...bounds, x1: 0.05 } }],
    }).success).toBe(false);
  });

  it("uses the typed workspace, queue, proposal, and attestation endpoints", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://leadtrace.test");
      if (url.pathname.endsWith("/workspace")) return jsonResponse(workspace);
      if (url.pathname.endsWith("/first-page-molecule-objects")) return jsonResponse(queue);
      if (url.pathname.endsWith("/attestation")) {
        return jsonResponse({
          id: ids.scope,
          changeset_id: ids.changeset,
          paper_id: ids.paper,
          changeset_version: 4,
          scope_hash: "b".repeat(64),
          item_count: 3,
          resolved_count: 3,
          blocker_count: 0,
          statement: "Reviewed all evidence",
          stale: false,
        });
      }
      if (url.pathname.endsWith(`/molecule-proposals/${ids.proposal}`)) {
        const { source_region_id: _sourceRegionId, ...apiProposal } = proposal;
        return jsonResponse({
          ...apiProposal,
          revision_number: 2,
          changeset_id: ids.changeset,
          changeset_version: 4,
          source_region: null,
        });
      }
      if (url.pathname.endsWith("/molecule-proposals")) return jsonResponse([]);
      throw new Error(`Unexpected request: ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    await fetchWorkspace(ids.changeset);
    await fetchMoleculeObjectQueue({ status: "proposal_review", page: 1, limit: 20 });
    await fetchMoleculeProposals(ids.paper);
    await updateMoleculeProposal(ids.paper, ids.proposal, {
      changeset_id: ids.changeset,
      expected_version: 3,
      disposition: "rejected",
      rationale: "Not a chemical structure",
    });
    await attestPaper(ids.changeset, {
      expected_version: 3,
      scope_hash: "b".repeat(64),
      statement: "Reviewed all evidence",
      confirmed: true,
    });

    const calls = fetchMock.mock.calls.map(([input, init]) => ({
      url: String(input),
      method: init?.method ?? "GET",
      csrf: new Headers(init?.headers).get("X-CSRF-Token"),
    }));
    expect(calls).toEqual([
      { url: `/api/v1/review/changesets/${ids.changeset}/workspace`, method: "GET", csrf: null },
      {
        url: "/api/v1/review/tasks/first-page-molecule-objects?status=proposal_review&page=1&limit=20",
        method: "GET",
        csrf: null,
      },
      { url: `/api/v1/papers/${ids.paper}/molecule-proposals`, method: "GET", csrf: null },
      {
        url: `/api/v1/papers/${ids.paper}/molecule-proposals/${ids.proposal}`,
        method: "PATCH",
        csrf: "reviewer-csrf",
      },
      {
        url: `/api/v1/review/changesets/${ids.changeset}/attestation`,
        method: "POST",
        csrf: "reviewer-csrf",
      },
    ]);
  });

  it("keeps the latest workspace load and applies deep-linked selection", async () => {
    let resolveFirst: ((response: Response) => void) | undefined;
    const firstResponse = new Promise<Response>((resolve) => {
      resolveFirst = resolve;
    });
    const secondChangeset = "20000000-0000-4000-8000-000000000002";
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path.includes(ids.changeset)) return firstResponse;
      return jsonResponse({
        ...workspace,
        workspace_version: 7,
        changeset: { ...workspace.changeset, id: secondChangeset, version: 7 },
      });
    }));
    const state = useWorkspace();

    const firstLoad = state.load(ids.changeset);
    await state.load(secondChangeset, {
      view: "ocsr",
      page: "1",
      object: ids.visual,
      proposal: ids.proposal,
    });
    resolveFirst?.(jsonResponse(workspace));
    await firstLoad;

    expect(state.workspace.value?.changeset.id).toBe(secondChangeset);
    expect(state.selectedView.value).toBe("ocsr");
    expect(state.selectedPage.value).toBe(1);
    expect(state.selectedVisualObjectId.value).toBe(ids.visual);
    expect(state.selectedProposalId.value).toBe(ids.proposal);
    expect(state.selectedRegionId.value).toBe(ids.region);
    expect(state.unresolvedVisualObjects.value).toHaveLength(1);
  });
});

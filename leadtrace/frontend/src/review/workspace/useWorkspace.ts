import { computed, ref } from "vue";

import { ApiError } from "../../api/client";
import { fetchWorkspace } from "../api";
import type {
  MoleculeProposal,
  Workspace,
  WorkspaceMoleculeProposal,
  WorkspaceRegion,
  WorkspaceVisualObject,
} from "./types";

export type WorkspaceView =
  | "overview"
  | "pdf"
  | "molecules"
  | "ocsr"
  | "scientific"
  | "diff"
  | "submit";

export type WorkspaceLoadState = "idle" | "loading" | "ready" | "not-found" | "error";

export interface WorkspaceDeepLink {
  view?: string | string[] | null;
  page?: string | string[] | null;
  region?: string | string[] | null;
  object?: string | string[] | null;
  proposal?: string | string[] | null;
}

const workspaceViews = new Set<WorkspaceView>([
  "overview",
  "pdf",
  "molecules",
  "ocsr",
  "scientific",
  "diff",
  "submit",
]);

function scalar(value: string | string[] | null | undefined): string | undefined {
  if (typeof value === "string") return value;
  return Array.isArray(value) ? value[0] : undefined;
}

export function useWorkspace() {
  const state = ref<WorkspaceLoadState>("idle");
  const workspace = ref<Workspace>();
  const requestId = ref<string>();
  const selectedView = ref<WorkspaceView>("overview");
  const selectedPage = ref<number>();
  const selectedRegionId = ref<string>();
  const selectedVisualObjectId = ref<string>();
  const selectedProposalId = ref<string>();
  let generation = 0;
  let activeChangesetId: string | undefined;

  const selectedRegion = computed<WorkspaceRegion | undefined>(() => (
    workspace.value?.regions.find((region) => region.id === selectedRegionId.value)
  ));
  const selectedVisualObject = computed<WorkspaceVisualObject | undefined>(() => (
    workspace.value?.visual_objects.find(
      (visual) => visual.id === selectedVisualObjectId.value,
    )
  ));
  const selectedProposal = computed<WorkspaceMoleculeProposal | undefined>(() => (
    workspace.value?.molecule_proposals.find(
      (proposal) => proposal.id === selectedProposalId.value,
    )
  ));
  const unresolvedVisualObjects = computed(() => (
    workspace.value?.visual_objects.filter((visual) => visual.blocking) ?? []
  ));

  function applyDeepLink(query: WorkspaceDeepLink = {}): void {
    const current = workspace.value;
    if (!current) return;
    const view = scalar(query.view);
    selectedView.value = view && workspaceViews.has(view as WorkspaceView)
      ? view as WorkspaceView
      : "overview";

    const page = Number.parseInt(scalar(query.page) ?? "", 10);
    selectedPage.value = Number.isInteger(page) && page > 0
      ? page
      : current.pages[0]?.page_number;

    const proposalId = scalar(query.proposal);
    const proposal = current.molecule_proposals.find((item) => item.id === proposalId);
    const visualId = scalar(query.object) ?? proposal?.visual_object_id;
    const visual = current.visual_objects.find((item) => item.id === visualId);
    const regionId = scalar(query.region) ?? visual?.region_id ?? proposal?.source_region_id;

    selectedProposalId.value = proposal?.id;
    selectedVisualObjectId.value = visual?.id;
    selectedRegionId.value = current.regions.some((region) => region.id === regionId)
      ? regionId ?? undefined
      : undefined;
    if (selectedRegion.value) selectedPage.value = selectedRegion.value.page_number;
  }

  async function load(changesetId: string, query: WorkspaceDeepLink = {}): Promise<void> {
    const loadGeneration = ++generation;
    activeChangesetId = changesetId;
    state.value = "loading";
    requestId.value = undefined;
    try {
      const payload = await fetchWorkspace(changesetId);
      if (loadGeneration !== generation || activeChangesetId !== changesetId) return;
      workspace.value = payload;
      applyDeepLink(query);
      state.value = "ready";
    } catch (error) {
      if (loadGeneration !== generation || activeChangesetId !== changesetId) return;
      workspace.value = undefined;
      requestId.value = error instanceof ApiError ? error.requestId : undefined;
      state.value = error instanceof ApiError && error.status === 404
        ? "not-found"
        : "error";
    }
  }

  async function refreshAfterConflict(): Promise<void> {
    if (!activeChangesetId) return;
    await load(activeChangesetId, {
      view: selectedView.value,
      page: selectedPage.value ? String(selectedPage.value) : undefined,
      region: selectedRegionId.value,
      object: selectedVisualObjectId.value,
      proposal: selectedProposalId.value,
    });
  }

  function selectVisualObject(visualObjectId: string): void {
    const visual = workspace.value?.visual_objects.find(
      (item) => item.id === visualObjectId,
    );
    if (!visual) return;
    selectedVisualObjectId.value = visual.id;
    selectedRegionId.value = visual.region_id ?? undefined;
    const proposal = workspace.value?.molecule_proposals.find(
      (item) => item.visual_object_id === visual.id,
    );
    selectedProposalId.value = proposal?.id;
    if (selectedRegion.value) selectedPage.value = selectedRegion.value.page_number;
  }

  function selectAdjacentUnresolved(direction: 1 | -1): void {
    const unresolved = unresolvedVisualObjects.value;
    if (!unresolved.length) return;
    const currentIndex = unresolved.findIndex(
      (item) => item.id === selectedVisualObjectId.value,
    );
    const nextIndex = currentIndex < 0
      ? 0
      : (currentIndex + direction + unresolved.length) % unresolved.length;
    selectVisualObject(unresolved[nextIndex].id);
  }

  function applyProposalUpdate(updated: MoleculeProposal): void {
    const current = workspace.value;
    if (!current) return;
    const index = current.molecule_proposals.findIndex(
      (proposal) => proposal.id === updated.id,
    );
    if (index < 0) return;
    const existing = current.molecule_proposals[index];
    const replacement: WorkspaceMoleculeProposal = {
      ...existing,
      revision_id: updated.revision_id,
      disposition: updated.disposition,
      machine: updated.machine,
      review: updated.review,
      crop_asset: updated.crop_asset,
    };
    current.molecule_proposals.splice(index, 1, replacement);
    if (updated.changeset_version) {
      current.workspace_version = updated.changeset_version;
      current.changeset.version = updated.changeset_version;
    }
    workspace.value = { ...current };
  }

  return {
    state,
    workspace,
    requestId,
    selectedView,
    selectedPage,
    selectedRegionId,
    selectedVisualObjectId,
    selectedProposalId,
    selectedRegion,
    selectedVisualObject,
    selectedProposal,
    unresolvedVisualObjects,
    load,
    applyDeepLink,
    refreshAfterConflict,
    selectVisualObject,
    selectAdjacentUnresolved,
    applyProposalUpdate,
  };
}

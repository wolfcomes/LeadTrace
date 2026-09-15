import { apiRequest } from "../api/client";
import { z } from "zod";
import {
  changesetItemSchema,
  changesetMutationSchema,
  changesetSchema,
  revisionDiffSchema,
  reviewTaskSchema,
  type Changeset,
  type ChangesetItem,
  type ChangesetMutation,
  type RevisionDiff,
  type ReviewTask,
} from "../api/schema";
import { useAuthStore } from "../auth/store";
import {
  moleculeObjectQueueSchema,
  moleculeProposalSchema,
  paperAttestationSchema,
  workspaceSchema,
  type MoleculeObjectQueue,
  type MoleculeObjectType,
  type MoleculeProposal,
  type MoleculeProposalDisposition,
  type PaperAttestation,
  type QueueState,
  type Workspace,
} from "./workspace/types";

function csrfToken(): string | null {
  return useAuthStore().csrfToken;
}

const visualObjectMutationSchema = z.object({
  id: z.string(),
  paper_id: z.string(),
  object_key: z.string(),
  object_type: z.string(),
  revision_id: z.string(),
  revision_number: z.number().int().positive(),
  changeset_id: z.string().nullable(),
  changeset_version: z.number().int().positive(),
  snapshot: z.record(z.string(), z.unknown()),
  workflow_state: z.string(),
}).strict();

const bindingMutationSchema = z.object({
  id: z.string(),
  region_id: z.string().optional(),
  asset_id: z.string().optional(),
  compound_id: z.string().optional(),
  label: z.string().optional(),
  operation: z.string().optional(),
}).strict();

const regionIdentitySchema = z.object({ id: z.string(), region_key: z.string() }).strict();
const regionRevisionSchema = z.object({
  revision_id: z.string(),
  revision_number: z.number().int().positive().optional(),
  is_tombstone: z.boolean().optional(),
}).strict();
const regionSplitSchema = z.object({ regions: regionIdentitySchema.array().length(2) }).strict();

export interface DraftMutationContext {
  changeset_id: string;
  expected_version: number;
}

export function createRegion(paperId: string, input: DraftMutationContext & {
  region_key: string;
  page_number: number;
  bounds: { x0: number; y0: number; x1: number; y1: number };
  rotation: number;
}) {
  return apiRequest(`/api/v1/papers/${encodeURIComponent(paperId)}/regions`, regionIdentitySchema, {
    method: "POST", csrfToken: csrfToken(), body: input,
  });
}

export function updateRegion(paperId: string, regionId: string, input: DraftMutationContext & {
  page_number?: number;
  bounds?: { x0: number; y0: number; x1: number; y1: number };
  rotation?: number;
}) {
  return apiRequest(`/api/v1/papers/${encodeURIComponent(paperId)}/regions/${encodeURIComponent(regionId)}`, regionRevisionSchema, {
    method: "PATCH", csrfToken: csrfToken(), body: input,
  });
}

export function duplicateRegion(paperId: string, regionId: string, input: DraftMutationContext & { region_key: string }) {
  return apiRequest(`/api/v1/papers/${encodeURIComponent(paperId)}/regions/${encodeURIComponent(regionId)}/duplicate`, regionIdentitySchema, {
    method: "POST", csrfToken: csrfToken(), body: input,
  });
}

export function splitRegion(paperId: string, regionId: string, input: DraftMutationContext & {
  first_key: string;
  second_key: string;
  first_bounds: { x0: number; y0: number; x1: number; y1: number };
  second_bounds: { x0: number; y0: number; x1: number; y1: number };
}) {
  return apiRequest(`/api/v1/papers/${encodeURIComponent(paperId)}/regions/${encodeURIComponent(regionId)}/split`, regionSplitSchema, {
    method: "POST", csrfToken: csrfToken(), body: input,
  });
}

export function setRegionTombstone(
  paperId: string,
  regionId: string,
  action: "tombstone" | "restore",
  input: DraftMutationContext,
) {
  return apiRequest(`/api/v1/papers/${encodeURIComponent(paperId)}/regions/${encodeURIComponent(regionId)}/${action}`, regionRevisionSchema, {
    method: "POST", csrfToken: csrfToken(), body: input,
  });
}

export function updateVisualObject(paperId: string, objectId: string, input: DraftMutationContext & {
  object_type: MoleculeObjectType;
  label?: string | null;
}) {
  return apiRequest(`/api/v1/papers/${encodeURIComponent(paperId)}/visual-objects/${encodeURIComponent(objectId)}`, visualObjectMutationSchema, {
    method: "PATCH", csrfToken: csrfToken(), body: input,
  });
}

export function bindVisualObjectRegion(paperId: string, objectId: string, input: DraftMutationContext & {
  region_id: string;
  role?: string;
  note?: string | null;
}) {
  return apiRequest(`/api/v1/papers/${encodeURIComponent(paperId)}/visual-objects/${encodeURIComponent(objectId)}/regions`, bindingMutationSchema, {
    method: "POST", csrfToken: csrfToken(), body: input,
  });
}

export function bindVisualObjectAsset(paperId: string, objectId: string, input: DraftMutationContext & {
  asset_id: string;
  role?: string;
  is_primary?: boolean;
}) {
  return apiRequest(`/api/v1/papers/${encodeURIComponent(paperId)}/visual-objects/${encodeURIComponent(objectId)}/assets`, bindingMutationSchema, {
    method: "POST", csrfToken: csrfToken(), body: input,
  });
}

export function bindVisualObjectCompound(paperId: string, objectId: string, input: DraftMutationContext & {
  compound_id: string;
  label: string;
  role?: string;
  confidence?: number | null;
  note?: string | null;
  is_primary?: boolean;
}) {
  return apiRequest(`/api/v1/papers/${encodeURIComponent(paperId)}/visual-objects/${encodeURIComponent(objectId)}/compounds`, bindingMutationSchema, {
    method: "POST", csrfToken: csrfToken(), body: input,
  });
}

export function updateVisualObjectAssetBinding(paperId: string, objectId: string, bindingId: string, input: DraftMutationContext & {
  role: string;
  is_primary: boolean;
}) {
  return apiRequest(`/api/v1/papers/${encodeURIComponent(paperId)}/visual-objects/${encodeURIComponent(objectId)}/assets/${encodeURIComponent(bindingId)}`, bindingMutationSchema, {
    method: "PATCH", csrfToken: csrfToken(), body: input,
  });
}

export function removeVisualObjectBinding(
  paperId: string,
  objectId: string,
  kind: "regions" | "assets" | "compounds",
  bindingId: string,
  input: DraftMutationContext,
) {
  return apiRequest(`/api/v1/papers/${encodeURIComponent(paperId)}/visual-objects/${encodeURIComponent(objectId)}/${kind}/${encodeURIComponent(bindingId)}`, bindingMutationSchema, {
    method: "DELETE", csrfToken: csrfToken(), body: input,
  });
}

export function fetchReviewTasks(): Promise<ReviewTask[]> {
  return apiRequest("/api/v1/review/tasks", reviewTaskSchema.array());
}

export function fetchWorkspace(changesetId: string): Promise<Workspace> {
  return apiRequest(
    `/api/v1/review/changesets/${encodeURIComponent(changesetId)}/workspace`,
    workspaceSchema,
  );
}

export interface MoleculeObjectQueueFilters {
  status?: QueueState;
  paper_id?: string;
  page?: number;
  object_type?: MoleculeObjectType;
  has_blocker?: boolean;
  cursor?: string;
  limit?: number;
}

export function fetchMoleculeObjectQueue(
  filters: MoleculeObjectQueueFilters = {},
): Promise<MoleculeObjectQueue> {
  const query = new URLSearchParams();
  if (filters.status) query.set("status", filters.status);
  if (filters.paper_id) query.set("paper_id", filters.paper_id);
  if (filters.page !== undefined) query.set("page", String(filters.page));
  if (filters.object_type) query.set("object_type", filters.object_type);
  if (filters.has_blocker !== undefined) {
    query.set("has_blocker", String(filters.has_blocker));
  }
  if (filters.cursor) query.set("cursor", filters.cursor);
  if (filters.limit !== undefined) query.set("limit", String(filters.limit));
  const suffix = query.size ? `?${query.toString()}` : "";
  return apiRequest(
    `/api/v1/review/tasks/first-page-molecule-objects${suffix}`,
    moleculeObjectQueueSchema,
  );
}

export function fetchMoleculeProposals(paperId: string): Promise<MoleculeProposal[]> {
  return apiRequest(
    `/api/v1/papers/${encodeURIComponent(paperId)}/molecule-proposals`,
    moleculeProposalSchema.array(),
  );
}

export interface MoleculeProposalUpdate {
  changeset_id: string;
  expected_version: number;
  disposition: MoleculeProposalDisposition;
  reviewed_smiles?: string | null;
  selected_component_smiles?: string | null;
  compound_id?: string | null;
  resulting_structure_id?: string | null;
  rationale?: string | null;
  source_comparison?: "match" | "mismatch" | "not_compared";
  source_verified?: boolean;
}

export function updateMoleculeProposal(
  paperId: string,
  proposalId: string,
  input: MoleculeProposalUpdate,
): Promise<MoleculeProposal> {
  return apiRequest(
    `/api/v1/papers/${encodeURIComponent(paperId)}/molecule-proposals/${encodeURIComponent(proposalId)}`,
    moleculeProposalSchema,
    { method: "PATCH", csrfToken: csrfToken(), body: input },
  );
}

export function attestPaper(
  changesetId: string,
  input: {
    expected_version: number;
    scope_hash: string;
    statement: string;
    confirmed: true;
  },
): Promise<PaperAttestation> {
  return apiRequest(
    `/api/v1/review/changesets/${encodeURIComponent(changesetId)}/attestation`,
    paperAttestationSchema,
    { method: "POST", csrfToken: csrfToken(), body: input },
  );
}

export function createReviewTask(input: {
  paper_id: string;
  assigned_reviewer_id: string;
  priority: number;
}): Promise<ReviewTask> {
  return apiRequest("/api/v1/review/tasks", reviewTaskSchema, {
    method: "POST",
    csrfToken: csrfToken(),
    body: input,
  });
}

export function fetchChangesets(): Promise<Changeset[]> {
  return apiRequest("/api/v1/review/changesets", changesetSchema.array());
}

export function fetchChangeset(changesetId: string): Promise<Changeset> {
  return apiRequest(`/api/v1/review/changesets/${encodeURIComponent(changesetId)}`, changesetSchema);
}

export function fetchChangesetItems(changesetId: string): Promise<ChangesetItem[]> {
  return apiRequest(
    `/api/v1/review/changesets/${encodeURIComponent(changesetId)}/items`,
    changesetItemSchema.array(),
  );
}

export function fetchChangesetDiff(changesetId: string): Promise<RevisionDiff[]> {
  return apiRequest(
    `/api/v1/review/changesets/${encodeURIComponent(changesetId)}/diff`,
    revisionDiffSchema.array(),
  );
}

export function createChangeset(input: {
  review_task_id: string;
  paper_id: string;
  base_release_id: string;
  title: string;
  reason: string;
  initialize_from_base?: boolean;
}): Promise<Changeset> {
  return apiRequest("/api/v1/review/changesets", changesetSchema, {
    method: "POST",
    csrfToken: csrfToken(),
    body: input,
  });
}

export function updateChangeset(
  changesetId: string,
  input: {
    expected_version: number;
    title?: string;
    reason?: string;
    validation_results?: Record<string, unknown>;
  },
): Promise<Changeset> {
  return apiRequest(
    `/api/v1/review/changesets/${encodeURIComponent(changesetId)}`,
    changesetSchema,
    { method: "PATCH", csrfToken: csrfToken(), body: input },
  );
}

export function createChangesetItem(
  changesetId: string,
  input: {
    expected_version: number;
    object_id: string;
    object_kind: ChangesetItem["object_kind"];
    base_revision_id?: string;
    proposed_snapshot: Record<string, unknown>;
    sequence?: number;
  },
): Promise<ChangesetItem> {
  return apiRequest(
    `/api/v1/review/changesets/${encodeURIComponent(changesetId)}/items`,
    changesetItemSchema,
    { method: "POST", csrfToken: csrfToken(), body: input },
  );
}

export function createChangesetItemFromBase(
  changesetId: string,
  input: {
    expected_version: number;
    object_id: string;
    object_kind: ChangesetItem["object_kind"];
    sequence?: number;
  },
): Promise<ChangesetItem> {
  return apiRequest(
    `/api/v1/review/changesets/${encodeURIComponent(changesetId)}/items/from-base`,
    changesetItemSchema,
    { method: "POST", csrfToken: csrfToken(), body: input },
  );
}

export function updateChangesetItem(
  changesetId: string,
  itemId: string,
  input: { expected_version: number; proposed_snapshot: Record<string, unknown> },
): Promise<ChangesetItem> {
  return apiRequest(
    `/api/v1/review/changesets/${encodeURIComponent(changesetId)}/items/${encodeURIComponent(itemId)}`,
    changesetItemSchema,
    { method: "PATCH", csrfToken: csrfToken(), body: input },
  );
}

export function deleteChangesetItem(
  changesetId: string,
  itemId: string,
  expectedVersion: number,
): Promise<ChangesetMutation> {
  return apiRequest(
    `/api/v1/review/changesets/${encodeURIComponent(changesetId)}/items/${encodeURIComponent(itemId)}`,
    changesetMutationSchema,
    {
      method: "DELETE",
      csrfToken: csrfToken(),
      body: { expected_version: expectedVersion },
    },
  );
}

export function submitChangeset(changesetId: string, expectedVersion: number): Promise<Changeset> {
  return apiRequest(
    `/api/v1/review/changesets/${encodeURIComponent(changesetId)}/submit`,
    changesetSchema,
    {
      method: "POST",
      csrfToken: csrfToken(),
      body: { expected_version: expectedVersion },
    },
  );
}

export function reviseChangeset(changesetId: string, expectedVersion: number): Promise<Changeset> {
  return apiRequest(
    `/api/v1/review/changesets/${encodeURIComponent(changesetId)}/revise`,
    changesetSchema,
    {
      method: "POST",
      csrfToken: csrfToken(),
      body: { expected_version: expectedVersion },
    },
  );
}

export function transitionChangeset(
  changesetId: string,
  path: "request-changes" | "reject" | "approve" | "publish" | "supersede",
  input: { expected_version: number; reason: string },
): Promise<Changeset> {
  return apiRequest(
    `/api/v1/review/changesets/${encodeURIComponent(changesetId)}/${path}`,
    changesetSchema,
    { method: "POST", csrfToken: csrfToken(), body: input },
  );
}

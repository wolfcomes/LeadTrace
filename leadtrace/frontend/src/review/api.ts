import { apiRequest } from "../api/client";
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

function csrfToken(): string | null {
  return useAuthStore().csrfToken;
}

export function fetchReviewTasks(): Promise<ReviewTask[]> {
  return apiRequest("/api/v1/review/tasks", reviewTaskSchema.array());
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

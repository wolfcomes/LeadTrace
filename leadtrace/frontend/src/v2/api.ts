import { apiRequest } from "../api/client";
import {
  adminSubmissionDetailSchema,
  adminSubmissionListSchema,
  assignmentResponseSchema,
  decisionMutationSchema,
  paperCatalogPageSchema,
  paperCatalogRowSchema,
  paperWorkspaceSchema,
  publishedPaperDetailSchema,
  publishedPaperListSchema,
  reviewTaskListSchema,
  submissionMutationSchema,
  type AdminSubmissionDetail,
  type AdminSubmissionList,
  type AssignmentResponse,
  type DecisionMutation,
  type PaperCatalogPage,
  type PaperCatalogRow,
  type PaperWorkspace,
  type PublishedPaperDetail,
  type PublishedPaperList,
  type ReviewTaskList,
  type SubmissionMutation,
} from "./types";


function withQuery(path: string, values: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined) query.set(key, String(value));
  }
  const encoded = query.toString();
  return encoded ? `${path}?${encoded}` : path;
}

export function listAdminPapers(
  options: { limit?: number; offset?: number; search?: string } = {},
): Promise<PaperCatalogPage> {
  return apiRequest(
    withQuery("/api/v2/admin/papers", options),
    paperCatalogPageSchema,
  );
}

export function getAdminPaper(paperId: string): Promise<PaperCatalogRow> {
  return apiRequest(`/api/v2/admin/papers/${encodeURIComponent(paperId)}`, paperCatalogRowSchema);
}

export function assignPaper(
  paperId: string,
  reviewerId: string,
  csrfToken: string | null,
): Promise<AssignmentResponse> {
  return apiRequest(
    `/api/v2/admin/papers/${encodeURIComponent(paperId)}/assign`,
    assignmentResponseSchema,
    { method: "POST", csrfToken, body: { reviewer_id: reviewerId } },
  );
}

export function listReviewTasks(): Promise<ReviewTaskList> {
  return apiRequest("/api/v2/review/tasks", reviewTaskListSchema);
}

export function getPaperWorkspace(workspaceId: string): Promise<PaperWorkspace> {
  return apiRequest(
    `/api/v2/workspaces/${encodeURIComponent(workspaceId)}`,
    paperWorkspaceSchema,
  );
}

export function updateBibliography(
  workspaceId: string,
  payload: Record<string, unknown> & { expected_workspace_version: number },
  csrfToken: string | null,
): Promise<PaperWorkspace> {
  return apiRequest(
    `/api/v2/workspaces/${encodeURIComponent(workspaceId)}/bibliography`,
    paperWorkspaceSchema,
    { method: "PATCH", csrfToken, body: payload },
  );
}

export function updateSection(
  workspaceId: string,
  section: string,
  payload: {
    expected_workspace_version: number;
    state: "pending" | "completed" | "not_reported";
    note?: string | null;
  },
  csrfToken: string | null,
): Promise<PaperWorkspace> {
  return apiRequest(
    `/api/v2/workspaces/${encodeURIComponent(workspaceId)}/sections/${encodeURIComponent(section)}`,
    paperWorkspaceSchema,
    { method: "PUT", csrfToken, body: payload },
  );
}

export function submitWorkspace(
  workspaceId: string,
  payload: {
    expected_workspace_version: number;
    reviewer_note?: string | null;
  },
  idempotencyKey: string,
  csrfToken: string | null,
): Promise<SubmissionMutation> {
  return apiRequest(
    `/api/v2/workspaces/${encodeURIComponent(workspaceId)}/submit`,
    submissionMutationSchema,
    {
      method: "POST",
      csrfToken,
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload,
    },
  );
}

export function listAdminSubmissions(): Promise<AdminSubmissionList> {
  return apiRequest("/api/v2/admin/submissions", adminSubmissionListSchema);
}

export function getAdminSubmission(submissionId: string): Promise<AdminSubmissionDetail> {
  return apiRequest(
    `/api/v2/admin/submissions/${encodeURIComponent(submissionId)}`,
    adminSubmissionDetailSchema,
  );
}

export function decideSubmission(
  submissionId: string,
  payload: {
    content_hash: string;
    action: "approve" | "request_changes";
    reason: string;
  },
  idempotencyKey: string,
  csrfToken: string | null,
): Promise<DecisionMutation> {
  return apiRequest(
    `/api/v2/admin/submissions/${encodeURIComponent(submissionId)}/decisions`,
    decisionMutationSchema,
    {
      method: "POST",
      csrfToken,
      headers: { "Idempotency-Key": idempotencyKey },
      body: payload,
    },
  );
}

export function listPublishedPapers(): Promise<PublishedPaperList> {
  return apiRequest("/api/v2/papers", publishedPaperListSchema);
}

export function getPublishedPaper(paperId: string): Promise<PublishedPaperDetail> {
  return apiRequest(`/api/v2/papers/${encodeURIComponent(paperId)}`, publishedPaperDetailSchema);
}

export function publishedAssetUrl(paperId: string, assetId: string): string {
  return `/api/v2/papers/${encodeURIComponent(paperId)}/assets/${encodeURIComponent(assetId)}`;
}

import { apiRequest } from "../api/client";
import {
  adminSubmissionDetailSchema,
  adminSubmissionListSchema,
  assignmentResponseSchema,
  compoundDeleteSchema,
  compoundListSchema,
  compoundMutationSchema,
  decisionMutationSchema,
  paperCatalogPageSchema,
  paperCatalogRowSchema,
  paperWorkspaceSchema,
  publishedPaperDetailSchema,
  publishedPaperListSchema,
  reviewTaskListSchema,
  structureMutationSchema,
  structureReadSchema,
  structureSourceImageDeleteSchema,
  structureSourceImageListSchema,
  structureSourceImageMutationSchema,
  submissionMutationSchema,
  type AdminSubmissionDetail,
  type AdminSubmissionList,
  type AssignmentResponse,
  type CompoundDelete,
  type CompoundList,
  type CompoundMutation,
  type DecisionMutation,
  type PaperCatalogPage,
  type PaperCatalogRow,
  type PaperWorkspace,
  type PublishedPaperDetail,
  type PublishedPaperList,
  type ReviewTaskList,
  type StructureMutation,
  type StructureRead,
  type StructureSourceImageDelete,
  type StructureSourceImageList,
  type StructureSourceImageMutation,
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

export function listCompounds(workspaceId: string): Promise<CompoundList> {
  return apiRequest(
    `/api/v2/workspaces/${encodeURIComponent(workspaceId)}/compounds`,
    compoundListSchema,
  );
}

export function createCompound(
  workspaceId: string,
  payload: {
    expected_workspace_version: number;
    compound_label: string;
    display_name?: string | null;
    description?: string | null;
  },
  csrfToken: string | null,
): Promise<CompoundMutation> {
  return apiRequest(
    `/api/v2/workspaces/${encodeURIComponent(workspaceId)}/compounds`,
    compoundMutationSchema,
    { method: "POST", csrfToken, body: payload },
  );
}

export function updateCompound(
  compoundId: string,
  payload: {
    expected_workspace_version: number;
    compound_label?: string;
    display_name?: string | null;
    description?: string | null;
  },
  csrfToken: string | null,
): Promise<CompoundMutation> {
  return apiRequest(
    `/api/v2/compounds/${encodeURIComponent(compoundId)}`,
    compoundMutationSchema,
    { method: "PATCH", csrfToken, body: payload },
  );
}

export function deleteCompound(
  compoundId: string,
  expectedWorkspaceVersion: number,
  csrfToken: string | null,
): Promise<CompoundDelete> {
  return apiRequest(
    `/api/v2/compounds/${encodeURIComponent(compoundId)}`,
    compoundDeleteSchema,
    { method: "DELETE", csrfToken, body: { expected_workspace_version: expectedWorkspaceVersion } },
  );
}

export function getCompoundStructure(compoundId: string): Promise<StructureRead> {
  return apiRequest(
    `/api/v2/compounds/${encodeURIComponent(compoundId)}/structure`,
    structureReadSchema,
  );
}

export function putCompoundStructure(
  compoundId: string,
  payload: {
    expected_workspace_version: number;
    status: "draft" | "reviewer_confirmed" | "unresolved" | "not_reported";
    input_method: "ai_prefill" | "manual_smiles" | "structure_editor";
    smiles: string | null;
    molfile: string | null;
  },
  csrfToken: string | null,
): Promise<StructureMutation> {
  return apiRequest(
    `/api/v2/compounds/${encodeURIComponent(compoundId)}/structure`,
    structureMutationSchema,
    { method: "PUT", csrfToken, body: payload },
  );
}

export function structureDepictionUrl(compoundId: string): string {
  return `/api/v2/compounds/${encodeURIComponent(compoundId)}/structure/depiction`;
}

export function listStructureSourceImages(compoundId: string): Promise<StructureSourceImageList> {
  return apiRequest(
    `/api/v2/compounds/${encodeURIComponent(compoundId)}/source-images`,
    structureSourceImageListSchema,
  );
}

export function createStructureSourceImage(
  compoundId: string,
  payload: {
    expected_workspace_version: number;
    source_sha256: string;
    page_number: number;
    bbox: { x0: number; y0: number; x1: number; y1: number };
    source_context?: string | null;
    label?: string | null;
    reviewer_note?: string | null;
  },
  csrfToken: string | null,
): Promise<StructureSourceImageMutation> {
  return apiRequest(
    `/api/v2/compounds/${encodeURIComponent(compoundId)}/source-images`,
    structureSourceImageMutationSchema,
    { method: "POST", csrfToken, body: payload },
  );
}

export function retryStructureSourceImage(
  sourceImageId: string,
  expectedWorkspaceVersion: number,
  csrfToken: string | null,
): Promise<StructureSourceImageMutation> {
  return apiRequest(
    `/api/v2/structure-source-images/${encodeURIComponent(sourceImageId)}/retry`,
    structureSourceImageMutationSchema,
    { method: "POST", csrfToken, body: { expected_workspace_version: expectedWorkspaceVersion } },
  );
}

export function deleteStructureSourceImage(
  sourceImageId: string,
  expectedWorkspaceVersion: number,
  csrfToken: string | null,
): Promise<StructureSourceImageDelete> {
  return apiRequest(
    `/api/v2/structure-source-images/${encodeURIComponent(sourceImageId)}`,
    structureSourceImageDeleteSchema,
    { method: "DELETE", csrfToken, body: { expected_workspace_version: expectedWorkspaceVersion } },
  );
}

export function structureSourceImageContentUrl(sourceImageId: string): string {
  return `/api/v2/structure-source-images/${encodeURIComponent(sourceImageId)}/content`;
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

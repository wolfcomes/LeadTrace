import { apiRequest } from "../api/client";
import {
  adminSubmissionDetailSchema,
  adminSubmissionListSchema,
  aiPrefillStatusSchema,
  activityDeleteSchema,
  activityListSchema,
  activityMutationSchema,
  assignmentResponseSchema,
  compoundDeleteSchema,
  compoundListSchema,
  compoundMutationSchema,
  decisionMutationSchema,
  deletedRecordSchema,
  evidenceLinkListSchema,
  evidenceLinkMutationSchema,
  evidenceListSchema,
  evidenceMutationSchema,
  lineageEdgeMutationSchema,
  lineageListSchema,
  lineageMemberMutationSchema,
  lineageMutationSchema,
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
  submissionValidationSchema,
  type AdminSubmissionDetail,
  type AdminSubmissionList,
  type AiPrefillStatus,
  type ActivityDelete,
  type ActivityList,
  type ActivityMutation,
  type AssignmentResponse,
  type CompoundDelete,
  type CompoundList,
  type CompoundMutation,
  type DecisionMutation,
  type DeletedRecord,
  type EvidenceLinkList,
  type EvidenceLinkMutation,
  type EvidenceList,
  type EvidenceMutation,
  type LineageEdgeMutation,
  type LineageList,
  type LineageMemberMutation,
  type LineageMutation,
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
  type SubmissionValidation,
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

export function getAiPrefillStatus(paperId: string): Promise<AiPrefillStatus> {
  return apiRequest(
    `/api/v2/admin/papers/${encodeURIComponent(paperId)}/ai-prefill`,
    aiPrefillStatusSchema,
  );
}

export function startAiPrefill(
  paperId: string,
  csrfToken: string | null,
): Promise<AiPrefillStatus> {
  return apiRequest(
    `/api/v2/admin/papers/${encodeURIComponent(paperId)}/ai-prefill`,
    aiPrefillStatusSchema,
    { method: "POST", csrfToken },
  );
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

export function listLineages(workspaceId: string): Promise<LineageList> {
  return apiRequest(`/api/v2/workspaces/${encodeURIComponent(workspaceId)}/lineages`, lineageListSchema);
}

export function createLineage(
  workspaceId: string,
  payload: { expected_workspace_version: number; lineage_label: string; description?: string | null },
  csrfToken: string | null,
): Promise<LineageMutation> {
  return apiRequest(`/api/v2/workspaces/${encodeURIComponent(workspaceId)}/lineages`, lineageMutationSchema, { method: "POST", csrfToken, body: payload });
}

export function updateLineage(
  lineageId: string,
  payload: { expected_workspace_version: number; lineage_label?: string; description?: string | null },
  csrfToken: string | null,
): Promise<LineageMutation> {
  return apiRequest(`/api/v2/lineages/${encodeURIComponent(lineageId)}`, lineageMutationSchema, { method: "PATCH", csrfToken, body: payload });
}

export function deleteLineage(lineageId: string, expectedWorkspaceVersion: number, csrfToken: string | null): Promise<DeletedRecord> {
  return apiRequest(`/api/v2/lineages/${encodeURIComponent(lineageId)}`, deletedRecordSchema, { method: "DELETE", csrfToken, body: { expected_workspace_version: expectedWorkspaceVersion } });
}

export function addLineageMember(
  lineageId: string,
  payload: { expected_workspace_version: number; compound_id: string; role: "root" | "intermediate" | "terminal" | "unspecified" },
  csrfToken: string | null,
): Promise<LineageMemberMutation> {
  return apiRequest(`/api/v2/lineages/${encodeURIComponent(lineageId)}/members`, lineageMemberMutationSchema, { method: "POST", csrfToken, body: payload });
}

export function updateLineageMember(
  memberId: string,
  payload: { expected_workspace_version: number; role: "root" | "intermediate" | "terminal" | "unspecified" },
  csrfToken: string | null,
): Promise<LineageMemberMutation> {
  return apiRequest(`/api/v2/lineage-members/${encodeURIComponent(memberId)}`, lineageMemberMutationSchema, { method: "PATCH", csrfToken, body: payload });
}

export function deleteLineageMember(memberId: string, expectedWorkspaceVersion: number, csrfToken: string | null): Promise<DeletedRecord> {
  return apiRequest(`/api/v2/lineage-members/${encodeURIComponent(memberId)}`, deletedRecordSchema, { method: "DELETE", csrfToken, body: { expected_workspace_version: expectedWorkspaceVersion } });
}

export function createLineageEdge(
  lineageId: string,
  payload: {
    expected_workspace_version: number;
    parent_compound_id: string;
    child_compound_id: string;
    relation_type: string;
    modification_summary?: string | null;
    review_status: "draft" | "reviewer_confirmed" | "unresolved";
  },
  csrfToken: string | null,
): Promise<LineageEdgeMutation> {
  return apiRequest(`/api/v2/lineages/${encodeURIComponent(lineageId)}/edges`, lineageEdgeMutationSchema, { method: "POST", csrfToken, body: payload });
}

export function updateLineageEdge(
  edgeId: string,
  payload: {
    expected_workspace_version: number;
    parent_compound_id?: string;
    child_compound_id?: string;
    review_status?: "draft" | "reviewer_confirmed" | "unresolved";
    relation_type?: string;
    modification_summary?: string | null;
  },
  csrfToken: string | null,
): Promise<LineageEdgeMutation> {
  return apiRequest(`/api/v2/lineage-edges/${encodeURIComponent(edgeId)}`, lineageEdgeMutationSchema, { method: "PATCH", csrfToken, body: payload });
}

export function deleteLineageEdge(edgeId: string, expectedWorkspaceVersion: number, csrfToken: string | null): Promise<DeletedRecord> {
  return apiRequest(`/api/v2/lineage-edges/${encodeURIComponent(edgeId)}`, deletedRecordSchema, { method: "DELETE", csrfToken, body: { expected_workspace_version: expectedWorkspaceVersion } });
}

export function listEvidence(workspaceId: string): Promise<EvidenceList> {
  return apiRequest(`/api/v2/workspaces/${encodeURIComponent(workspaceId)}/evidence`, evidenceListSchema);
}

export function createEvidence(
  workspaceId: string,
  payload: {
    expected_workspace_version: number;
    kind: "text" | "table" | "scheme" | "image";
    source_sha256: string;
    page_number: number;
    bbox?: { x0: number; y0: number; x1: number; y1: number } | null;
    quoted_text?: string | null;
    caption?: string | null;
    reviewer_note?: string | null;
  },
  csrfToken: string | null,
): Promise<EvidenceMutation> {
  return apiRequest(`/api/v2/workspaces/${encodeURIComponent(workspaceId)}/evidence`, evidenceMutationSchema, { method: "POST", csrfToken, body: payload });
}

export function updateEvidence(
  evidenceId: string,
  payload: {
    expected_workspace_version: number;
    kind?: "text" | "table" | "scheme" | "image";
    source_sha256?: string;
    page_number?: number;
    bbox?: { x0: number; y0: number; x1: number; y1: number } | null;
    quoted_text?: string | null;
    caption?: string | null;
    reviewer_note?: string | null;
  },
  csrfToken: string | null,
): Promise<EvidenceMutation> {
  return apiRequest(`/api/v2/evidence/${encodeURIComponent(evidenceId)}`, evidenceMutationSchema, { method: "PATCH", csrfToken, body: payload });
}

export function deleteEvidence(evidenceId: string, expectedWorkspaceVersion: number, csrfToken: string | null): Promise<DeletedRecord> {
  return apiRequest(`/api/v2/evidence/${encodeURIComponent(evidenceId)}`, deletedRecordSchema, { method: "DELETE", csrfToken, body: { expected_workspace_version: expectedWorkspaceVersion } });
}

export function listEvidenceLinks(edgeId: string): Promise<EvidenceLinkList> {
  return apiRequest(`/api/v2/lineage-edges/${encodeURIComponent(edgeId)}/evidence-links`, evidenceLinkListSchema);
}

export function createEvidenceLink(
  edgeId: string,
  payload: { expected_workspace_version: number; evidence_id: string; role: "supports" | "contradicts" | "contextual" },
  csrfToken: string | null,
): Promise<EvidenceLinkMutation> {
  return apiRequest(`/api/v2/lineage-edges/${encodeURIComponent(edgeId)}/evidence-links`, evidenceLinkMutationSchema, { method: "POST", csrfToken, body: payload });
}

export function deleteEvidenceLink(linkId: string, expectedWorkspaceVersion: number, csrfToken: string | null): Promise<DeletedRecord> {
  return apiRequest(`/api/v2/edge-evidence-links/${encodeURIComponent(linkId)}`, deletedRecordSchema, { method: "DELETE", csrfToken, body: { expected_workspace_version: expectedWorkspaceVersion } });
}

export function listActivities(compoundId: string): Promise<ActivityList> {
  return apiRequest(`/api/v2/compounds/${encodeURIComponent(compoundId)}/activities`, activityListSchema);
}

export function createActivity(
  compoundId: string,
  payload: {
    expected_workspace_version: number;
    evidence_id?: string | null;
    assay_name: string;
    metric: string;
    operator: "=" | "<" | "<=" | ">" | ">=" | "~";
    value: string | number;
    unit?: string | null;
    context?: string | null;
  },
  csrfToken: string | null,
): Promise<ActivityMutation> {
  return apiRequest(`/api/v2/compounds/${encodeURIComponent(compoundId)}/activities`, activityMutationSchema, { method: "POST", csrfToken, body: payload });
}

export function updateActivity(
  activityId: string,
  payload: {
    expected_workspace_version: number;
    evidence_id?: string | null;
    assay_name?: string;
    metric?: string;
    operator?: "=" | "<" | "<=" | ">" | ">=" | "~";
    value?: string | number;
    unit?: string | null;
    context?: string | null;
  },
  csrfToken: string | null,
): Promise<ActivityMutation> {
  return apiRequest(`/api/v2/activities/${encodeURIComponent(activityId)}`, activityMutationSchema, { method: "PATCH", csrfToken, body: payload });
}

export function deleteActivity(activityId: string, expectedWorkspaceVersion: number, csrfToken: string | null): Promise<ActivityDelete> {
  return apiRequest(`/api/v2/activities/${encodeURIComponent(activityId)}`, activityDeleteSchema, { method: "DELETE", csrfToken, body: { expected_workspace_version: expectedWorkspaceVersion } });
}

export function getSubmissionValidation(workspaceId: string): Promise<SubmissionValidation> {
  return apiRequest(`/api/v2/workspaces/${encodeURIComponent(workspaceId)}/submission-validation`, submissionValidationSchema);
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

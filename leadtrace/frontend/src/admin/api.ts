import { apiRequest } from "../api/client";
import { useAuthStore } from "../auth/store";
import { z } from "zod";

const anyList = z.array(z.record(z.string(), z.unknown()));
const anyObject = z.record(z.string(), z.unknown());
const userSchema = z.object({ id: z.string().uuid(), username: z.string(), display_name: z.string(), role: z.enum(["visitor", "reviewer", "admin"]), is_enabled: z.boolean(), must_change_password: z.boolean() });
const usersSchema = userSchema.array();
const importCandidateDecisionSchema = z.object({
  id: z.string().uuid(),
  decision: z.enum(["approve", "reject"]),
  actor_id: z.string().uuid(),
  reason: z.string(),
  manifest_hash: z.string().length(64),
  created_at: z.string(),
});
const assetLinkageSchema = z.object({
  resolved_references: z.number().int().nonnegative(),
  unique_resolved_assets: z.number().int().nonnegative(),
  missing_references: z.number().int().nonnegative(),
  ambiguous_references: z.number().int().nonnegative(),
  corrupt_references: z.number().int().nonnegative(),
});
export const importCandidateSchema = z.object({
  id: z.string().uuid(),
  import_batch_id: z.string().uuid(),
  status: z.enum(["imported_baseline", "approved", "rejected", "published"]),
  is_current: z.boolean(),
  manifest: z.object({
    schema_version: z.number().int().positive().optional(),
    source_fingerprint: z.string().optional(),
    status: z.string().optional(),
    is_current: z.boolean().optional(),
    counts: z.record(z.string(), z.unknown()).optional(),
    integrity: z.record(z.string(), z.unknown()).optional(),
    asset_linkage: assetLinkageSchema.optional(),
    revision_count: z.number().int().nonnegative().optional(),
  }),
  decision: importCandidateDecisionSchema.nullable(),
  created_at: z.string(),
  idempotent: z.boolean().optional(),
  request_id: z.string().optional(),
});

export const adminPaperWorkflowSchema = z.enum([
  "initial",
  "ai_baseline_unassigned",
  "ai_baseline_in_review",
  "human_review_pending_approval",
  "admin_approved",
]);
const publicationStatusSchema = z.enum(["unpublished", "published"]);
const adminPaperSourceSchema = z.object({
  kind: z.enum(["candidate", "release", "database"]),
  candidate_id: z.string().uuid().nullable(),
  release_id: z.string().uuid().nullable(),
  title: z.string(),
  status: z.string(),
  dataset_class: z.string(),
  verification_status: z.string(),
  publication_status: publicationStatusSchema,
});
const adminPaperQualitySchema = z.object({
  compounds: z.number().int().nonnegative(),
  structures: z.number().int().nonnegative(),
  confirmed_structures: z.number().int().nonnegative(),
  evidence: z.number().int().nonnegative(),
  activities: z.number().int().nonnegative(),
  lineages: z.number().int().nonnegative(),
  lineage_edges: z.number().int().nonnegative(),
  unresolved_relations: z.number().int().nonnegative(),
  visual_objects: z.number().int().nonnegative(),
});
const adminPaperTaskSchema = z.object({
  id: z.string().uuid(),
  status: z.string(),
  assignee_id: z.string().uuid(),
  assignee_display_name: z.string(),
  priority: z.number().int().nonnegative(),
  version: z.number().int().positive(),
  updated_at: z.string(),
});
const adminPaperChangesetSchema = z.object({
  id: z.string().uuid(),
  workflow_state: z.string(),
  version: z.number().int().positive(),
  updated_at: z.string(),
});
export const adminPaperSchema = z.object({
  id: z.string().uuid(),
  revision_id: z.string().uuid().nullable(),
  paper_key: z.string(),
  doi: z.string().nullable(),
  title: z.string(),
  year: z.string().nullable(),
  target: z.string().nullable(),
  review_status: z.string().nullable(),
  workflow_state: adminPaperWorkflowSchema,
  publication_status: publicationStatusSchema,
  verification_status: z.string(),
  quality: adminPaperQualitySchema,
  task: adminPaperTaskSchema.nullable(),
  changeset: adminPaperChangesetSchema.nullable(),
  can_modify: z.boolean(),
  modification_blocker: z.string().nullable(),
});
export const adminPaperListSchema = z.object({
  request_id: z.string(),
  source: adminPaperSourceSchema,
  status_counts: z.record(adminPaperWorkflowSchema, z.number().int().nonnegative()),
  pagination: z.object({
    page: z.number().int().positive(),
    page_size: z.number().int().positive(),
    total_items: z.number().int().nonnegative(),
    total_pages: z.number().int().nonnegative(),
  }),
  filters: z.record(z.string(), z.unknown()),
  items: adminPaperSchema.array(),
});
export const adminPaperDetailSchema = z.object({
  request_id: z.string(),
  source: adminPaperSourceSchema,
  paper: adminPaperSchema,
  source_pdf_url: z.string(),
  review_entry: z.string().nullable(),
});

function csrfToken(): string | null { return useAuthStore().csrfToken; }
function csrfOptions(method: string, body?: unknown): Parameters<typeof apiRequest>[2] { return { method, csrfToken: csrfToken(), body }; }

export type AdminUser = z.infer<typeof userSchema>;
export type ImportCandidate = z.infer<typeof importCandidateSchema>;
export type AdminPaperWorkflow = z.infer<typeof adminPaperWorkflowSchema>;
export type AdminPaper = z.infer<typeof adminPaperSchema>;
export type AdminPaperList = z.infer<typeof adminPaperListSchema>;
export type AdminPaperDetail = z.infer<typeof adminPaperDetailSchema>;
export function fetchAdminUsers(): Promise<AdminUser[]> { return apiRequest("/api/v1/users", usersSchema); }
export function createAdminUser(input: Record<string, unknown>): Promise<AdminUser> { return apiRequest("/api/v1/users", userSchema, { ...csrfOptions("POST", input) }); }
export function resetUserToDefault(id: string): Promise<AdminUser> { return apiRequest(`/api/v1/users/${encodeURIComponent(id)}/password`, userSchema, csrfOptions("PATCH")); }
export function updateUserEnabled(id: string, is_enabled: boolean): Promise<AdminUser> { return apiRequest(`/api/v1/users/${encodeURIComponent(id)}/enabled`, userSchema, csrfOptions("PATCH", { is_enabled })); }
export function revokeUserSessions(id: string): Promise<undefined> { return apiRequest(`/api/v1/users/${encodeURIComponent(id)}/sessions/revoke`, z.undefined(), csrfOptions("POST")); }

export function fetchAdminFiles(): Promise<Record<string, unknown>[]> { return apiRequest("/api/v1/admin/files", anyList); }
export function fetchFileReferences(id: string): Promise<Record<string, unknown>> { return apiRequest(`/api/v1/admin/files/${encodeURIComponent(id)}/references`, anyObject); }
export function fetchAdminImports(): Promise<Record<string, unknown>[]> { return apiRequest("/api/v1/admin/imports", anyList); }
export function fetchImportCandidates(): Promise<ImportCandidate[]> { return apiRequest("/api/v1/admin/import-candidates", importCandidateSchema.array()); }
export function fetchAdminPapers(params: Record<string, string> = {}): Promise<AdminPaperList> {
  const query = new URLSearchParams(params).toString();
  return apiRequest(`/api/v1/admin/papers${query ? `?${query}` : ""}`, adminPaperListSchema);
}
export function fetchAdminPaper(id: string, candidateId?: string): Promise<AdminPaperDetail> {
  const query = candidateId ? `?candidate_id=${encodeURIComponent(candidateId)}` : "";
  return apiRequest(`/api/v1/admin/papers/${encodeURIComponent(id)}${query}`, adminPaperDetailSchema);
}
export function decideImportCandidate(
  id: string,
  action: "approve" | "reject",
  reason: string,
): Promise<ImportCandidate> {
  return apiRequest(
    `/api/v1/admin/import-candidates/${encodeURIComponent(id)}/decision`,
    importCandidateSchema,
    csrfOptions("POST", { action, reason }),
  );
}
export function dryRunImport(source_root: string): Promise<Record<string, unknown>> { return apiRequest("/api/v1/admin/imports/dry-run", anyObject, { ...csrfOptions("POST", { source_root }) }); }
export function applyImport(source_root: string): Promise<Record<string, unknown>> { return apiRequest("/api/v1/admin/imports/apply", anyObject, { ...csrfOptions("POST", { source_root }) }); }
export function fetchAdminAudit(params: Record<string, string> = {}): Promise<Record<string, unknown>[]> {
  const query = new URLSearchParams(params).toString();
  return apiRequest(`/api/v1/admin/audit${query ? `?${query}` : ""}`, anyList);
}
export function fetchAdminJobs(): Promise<Record<string, unknown>[]> { return apiRequest("/api/v1/admin/jobs", anyList); }
export function retryAdminJob(id: string): Promise<Record<string, unknown>> { return apiRequest(`/api/v1/admin/jobs/${encodeURIComponent(id)}/retry`, anyObject, { ...csrfOptions("POST"), headers: { "Idempotency-Key": `admin-retry-${id}` } }); }
export function fetchSystemHealth(): Promise<Record<string, unknown>> { return apiRequest("/api/v1/admin/system", anyObject); }

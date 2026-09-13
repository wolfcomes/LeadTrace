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

function csrfToken(): string | null { return useAuthStore().csrfToken; }
function csrfOptions(method: string, body?: unknown): Parameters<typeof apiRequest>[2] { return { method, csrfToken: csrfToken(), body }; }

export type AdminUser = z.infer<typeof userSchema>;
export type ImportCandidate = z.infer<typeof importCandidateSchema>;
export function fetchAdminUsers(): Promise<AdminUser[]> { return apiRequest("/api/v1/users", usersSchema); }
export function createAdminUser(input: Record<string, unknown>): Promise<AdminUser> { return apiRequest("/api/v1/users", userSchema, { ...csrfOptions("POST", input) }); }
export function resetUserToDefault(id: string): Promise<AdminUser> { return apiRequest(`/api/v1/users/${encodeURIComponent(id)}/password`, userSchema, csrfOptions("PATCH")); }
export function updateUserEnabled(id: string, is_enabled: boolean): Promise<AdminUser> { return apiRequest(`/api/v1/users/${encodeURIComponent(id)}/enabled`, userSchema, csrfOptions("PATCH", { is_enabled })); }
export function revokeUserSessions(id: string): Promise<undefined> { return apiRequest(`/api/v1/users/${encodeURIComponent(id)}/sessions/revoke`, z.undefined(), csrfOptions("POST")); }

export function fetchAdminFiles(): Promise<Record<string, unknown>[]> { return apiRequest("/api/v1/admin/files", anyList); }
export function fetchFileReferences(id: string): Promise<Record<string, unknown>> { return apiRequest(`/api/v1/admin/files/${encodeURIComponent(id)}/references`, anyObject); }
export function fetchAdminImports(): Promise<Record<string, unknown>[]> { return apiRequest("/api/v1/admin/imports", anyList); }
export function fetchImportCandidates(): Promise<ImportCandidate[]> { return apiRequest("/api/v1/admin/import-candidates", importCandidateSchema.array()); }
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

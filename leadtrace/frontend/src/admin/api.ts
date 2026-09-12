import { apiRequest } from "../api/client";
import { useAuthStore } from "../auth/store";
import { z } from "zod";

const anyList = z.array(z.record(z.string(), z.unknown()));
const anyObject = z.record(z.string(), z.unknown());
const userSchema = z.object({ id: z.string().uuid(), username: z.string(), display_name: z.string(), role: z.enum(["visitor", "reviewer", "admin"]), is_enabled: z.boolean(), must_change_password: z.boolean() });
const usersSchema = userSchema.array();

function csrfToken(): string | null { return useAuthStore().csrfToken; }
function csrfOptions(method: string, body?: unknown): Parameters<typeof apiRequest>[2] { return { method, csrfToken: csrfToken(), body }; }

export type AdminUser = z.infer<typeof userSchema>;
export function fetchAdminUsers(): Promise<AdminUser[]> { return apiRequest("/api/v1/users", usersSchema); }
export function createAdminUser(input: Record<string, unknown>): Promise<AdminUser> { return apiRequest("/api/v1/users", userSchema, { ...csrfOptions("POST", input) }); }
export function updateUserEnabled(id: string, is_enabled: boolean): Promise<AdminUser> { return apiRequest(`/api/v1/users/${encodeURIComponent(id)}/enabled`, userSchema, csrfOptions("PATCH", { is_enabled })); }
export function revokeUserSessions(id: string): Promise<undefined> { return apiRequest(`/api/v1/users/${encodeURIComponent(id)}/sessions/revoke`, z.undefined(), csrfOptions("POST")); }

export function fetchAdminFiles(): Promise<Record<string, unknown>[]> { return apiRequest("/api/v1/admin/files", anyList); }
export function fetchFileReferences(id: string): Promise<Record<string, unknown>> { return apiRequest(`/api/v1/admin/files/${encodeURIComponent(id)}/references`, anyObject); }
export function fetchAdminImports(): Promise<Record<string, unknown>[]> { return apiRequest("/api/v1/admin/imports", anyList); }
export function dryRunImport(source_root: string): Promise<Record<string, unknown>> { return apiRequest("/api/v1/admin/imports/dry-run", anyObject, { ...csrfOptions("POST", { source_root }) }); }
export function applyImport(source_root: string): Promise<Record<string, unknown>> { return apiRequest("/api/v1/admin/imports/apply", anyObject, { ...csrfOptions("POST", { source_root }) }); }
export function fetchAdminAudit(params: Record<string, string> = {}): Promise<Record<string, unknown>[]> {
  const query = new URLSearchParams(params).toString();
  return apiRequest(`/api/v1/admin/audit${query ? `?${query}` : ""}`, anyList);
}
export function fetchAdminJobs(): Promise<Record<string, unknown>[]> { return apiRequest("/api/v1/admin/jobs", anyList); }
export function retryAdminJob(id: string): Promise<Record<string, unknown>> { return apiRequest(`/api/v1/admin/jobs/${encodeURIComponent(id)}/retry`, anyObject, { ...csrfOptions("POST"), headers: { "Idempotency-Key": `admin-retry-${id}` } }); }
export function fetchSystemHealth(): Promise<Record<string, unknown>> { return apiRequest("/api/v1/admin/system", anyObject); }

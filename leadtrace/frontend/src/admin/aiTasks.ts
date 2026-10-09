import { z } from "zod";
import { apiRequest } from "../api/client";
import { useAuthStore } from "../auth/store";

export const aiPresetSchema = z.object({
  id: z.string(),
  label: z.string(),
  adapter: z.enum(["dsh", "codex"]),
  model: z.string(),
  efforts: z.array(z.string()),
  default_effort: z.string(),
  available: z.boolean(),
  unavailable_reason: z.string().nullable(),
});
export const aiJobSchema = z.object({
  id: z.string(),
  paper_id: z.string(),
  paper_key: z.string(),
  paper_title: z.string(),
  workspace_id: z.string().nullable(),
  workspace_version: z.number().nullable(),
  action: z.enum(["prefill", "review", "repair"]),
  preset_id: z.string(),
  model: z.string(),
  reasoning_effort: z.string(),
  state: z.string(),
  delivery_state: z.string(),
  stage: z.string(),
  error_code: z.string().nullable(),
  error_message: z.string().nullable(),
  created_at: z.string(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
  heartbeat_at: z.string().nullable(),
  timeout_seconds: z.number(),
  attempt: z.number(),
  parent_job_id: z.string().nullable(),
  result_summary: z.record(z.unknown()),
  can_deliver: z.boolean().optional(),
  can_repair: z.boolean().optional(),
  can_accept: z.boolean().optional(),
  can_cancel: z.boolean(),
  can_retry: z.boolean(),
});
const settingsSchema = z.object({
  max_concurrent: z.number().int().min(1).max(16),
});
const optionsShape = {
  settings: settingsSchema,
  worker: z.object({
    online: z.boolean(),
    last_seen_at: z.string().nullable(),
  }),
  presets: z.array(aiPresetSchema),
};
export const aiTaskPageSchema = z.object({
  ...optionsShape,
  items: z.array(aiJobSchema),
  total: z.number(),
});
export const paperManagementSchema = z.object({
  paper_id: z.string(),
  paper_key: z.string(),
  workspace_id: z.string().nullable(),
  workspace_version: z.number().nullable(),
  task_version: z.number().nullable(),
  assignment_state: z.enum([
    "unassigned",
    "assigned",
    "changes_requested",
    "submitted",
    "approved",
    "archived",
  ]),
  assigned_reviewer_id: z.string().nullable(),
  counts: z.record(z.number()),
  archives: z.array(
    z.object({
      id: z.string(),
      created_at: z.string(),
      relative_path: z.string(),
      workspace_id: z.string().nullable(),
    }),
  ),
  archive_root: z.string(),
});
export type AiPreset = z.infer<typeof aiPresetSchema>;
export type AiJob = z.infer<typeof aiJobSchema>;
export type AiTaskPage = z.infer<typeof aiTaskPageSchema>;
export type PaperManagement = z.infer<typeof paperManagementSchema>;
export interface StartAiTask {
  action: "prefill" | "review";
  preset_id: string;
  reasoning_effort: string;
  timeout_seconds: number;
  expected_workspace_version: number | null;
  expected_workspace_id: string | null;
  expected_task_version: number | null;
  idempotency_key: string;
  auto_review?: { preset_id: string; reasoning_effort: string } | null;
}
function mutation(method: string, body?: unknown) {
  return { method, body, csrfToken: useAuthStore().csrfToken };
}
export function fetchAiTasks(paperId?: string): Promise<AiTaskPage> {
  return apiRequest(
    `/api/v2/admin/ai-tasks${paperId ? `?paper_id=${encodeURIComponent(paperId)}` : ""}`,
    aiTaskPageSchema,
  );
}
export function changeAiConcurrency(max_concurrent: number) {
  return apiRequest(
    "/api/v2/admin/ai-tasks/settings",
    settingsSchema,
    mutation("PUT", { max_concurrent }),
  );
}
export function createAiTask(
  paperId: string,
  input: StartAiTask,
): Promise<AiJob> {
  return apiRequest(
    `/api/v2/admin/papers/${encodeURIComponent(paperId)}/ai-tasks`,
    aiJobSchema,
    mutation("POST", input),
  );
}
export function cancelAiTask(id: string): Promise<AiJob> {
  return apiRequest(
    `/api/v2/admin/ai-tasks/${encodeURIComponent(id)}/cancel`,
    aiJobSchema,
    mutation("POST"),
  );
}
export function retryAiTask(
  id: string,
  idempotency_key: string,
): Promise<AiJob> {
  return apiRequest(
    `/api/v2/admin/ai-tasks/${encodeURIComponent(id)}/retry`,
    aiJobSchema,
    mutation("POST", { idempotency_key }),
  );
}
export function fetchPaperManagement(
  paperId: string,
): Promise<PaperManagement> {
  return apiRequest(
    `/api/v2/admin/papers/${encodeURIComponent(paperId)}/management`,
    paperManagementSchema,
  );
}
type ExpectedVersions = {
  expected_workspace_id: string;
  expected_workspace_version: number;
  expected_task_version: number;
};
export function recallPaper(
  paperId: string,
  input: ExpectedVersions,
): Promise<PaperManagement> {
  return apiRequest(
    `/api/v2/admin/papers/${encodeURIComponent(paperId)}/recall`,
    paperManagementSchema,
    mutation("POST", input),
  );
}
export function archiveResetPaper(
  paperId: string,
  input: ExpectedVersions & { confirm_paper_key: string },
): Promise<PaperManagement> {
  return apiRequest(
    `/api/v2/admin/papers/${encodeURIComponent(paperId)}/archive-reset`,
    paperManagementSchema,
    mutation("POST", input),
  );
}
const reviewFindingSchema = z.object({
  domain: z.string(),
  ref: z.string(),
  verdict: z.string(),
  reason: z.string(),
  source_locator: z.string().optional(),
  checked_fields: z.array(z.string()).optional(),
  field_results: z.unknown().optional(),
});
export const aiOverviewSchema = z.object({
  schema_version: z.literal(1),
  basis: z.enum(['producer', 'independent_review']),
  entities: z.array(z.object({domain: z.string(), total: z.number(), supported: z.number().nullable(), incorrect: z.number().nullable(), uncertain: z.number().nullable(), unreviewed: z.number(), flagged: z.number()})),
  compound_coverage: z.object({known: z.boolean(), covered: z.number().nullable(), expected: z.number().nullable(), percent: z.number().nullable()}),
  audit_coverage: z.object({known: z.boolean(), checked: z.number(), expected: z.number().nullable(), percent: z.number().nullable()}),
  audit_scope: z.enum(['candidate_and_inventory', 'candidate_only']).optional(),
  screenshot_counts: z.object({structure_occurrences: z.number(), evidence_crops: z.number(), unique_crop_regions: z.number()}).optional(),
  limitations: z.array(z.string()).optional(),
  issue_groups: z.array(z.object({code: z.string(), count: z.number()})),
  highlights: z.array(z.union([z.string(), z.object({code:z.string(), ref:z.string(), summary:z.string()})])),
  unique_crop_regions: z.number(),
});
export const aiRepairProposalSchema = z.object({
  sha256: z.string(),
  counts: z.record(z.object({added: z.number(), updated: z.number(), removed: z.number()})),
  total_changes: z.number(),
  changes: z.array(z.object({domain: z.string(), ref: z.string(), action: z.string(), before: z.unknown(), after: z.unknown()})),
  remaining_findings: z.number(),
});
export const aiReviewReportSchema = z.object({
  report_kind: z.enum(['prefill', 'review', 'repair']).optional(),
  repair_proposal_status: z.enum(['ready', 'no_changes', 'unavailable']).nullish(),
  repair_proposal_errors: z.array(z.string()).optional(),
  repair_proposal_reason: z.string().nullish(),
  overview: aiOverviewSchema.optional(),
  proposal: aiRepairProposalSchema.nullish(),
  candidate_file_sha256: z.string().optional(),
  status: z.string().optional(),
  scientific_approval: z.literal(false).optional(),
  coverage_known: z.boolean().optional(),
  checks: z.array(z.object({ check_id: z.string(), status: z.string(), details: z.string() })).optional(),
  issue_counts: z.object({ blocking: z.number(), review: z.number() }).optional(),
  findings_total: z.number().optional(),
  delivery_notes: z.array(z.object({code: z.string(), compound_ref: z.string(), page_number: z.number(), locator_refs: z.array(z.string()), message: z.string(), extended_annotations: z.boolean().optional(), annotations: z.array(z.object({ref: z.string(), label: z.string().nullable(), source_context: z.string().nullable()})).optional()})).optional(),
  findings_truncated: z.boolean().optional(),
  job_id: z.string(),
  reviewed_workspace_version: z.number().nullable(),
  coverage: z.object({
    expected: z.number(),
    reviewed: z.number(),
    missing: z.array(z.object({ domain: z.string(), ref: z.string() })),
  }),
  findings: z.array(reviewFindingSchema),
});
export type AiReviewReport = z.infer<typeof aiReviewReportSchema>;
export function fetchAiReviewReport(id: string): Promise<AiReviewReport> {
  return apiRequest(
    `/api/v2/admin/ai-tasks/${encodeURIComponent(id)}/report`,
    aiReviewReportSchema,
  );
}

export function deliverAiTask(id: string): Promise<AiJob> {
  return apiRequest(`/api/v2/admin/ai-tasks/${encodeURIComponent(id)}/deliver`, aiJobSchema, mutation("POST"));
}

export interface StartAiRepair {
  preset_id: string;
  reasoning_effort: string;
  timeout_seconds: number;
  idempotency_key: string;
}
export function repairAiTask(id: string, input: StartAiRepair): Promise<AiJob> {
  return apiRequest(`/api/v2/admin/ai-tasks/${encodeURIComponent(id)}/repair`, aiJobSchema, mutation('POST', input));
}
export function acceptAiRepair(id: string, proposal_sha256: string): Promise<AiJob> {
  return apiRequest(`/api/v2/admin/ai-tasks/${encodeURIComponent(id)}/accept`, aiJobSchema, mutation('POST', {proposal_sha256}));
}

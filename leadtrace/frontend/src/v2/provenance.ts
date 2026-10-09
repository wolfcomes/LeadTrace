import { z } from 'zod';
import { apiRequest } from '../api/client';
export const aiProvenanceSchema = z.object({
  run_key: z.string(), stage: z.enum(['prefill','producer_self_check','repair','independent_review']),
  adapter: z.string().nullable().optional(), model: z.string().nullable().optional(),
  reasoning_effort: z.string().nullable().optional(), observed_model: z.string().nullable().optional(),
  observed_reasoning_effort: z.string().nullable().optional(),
  verification: z.enum(['unknown','candidate_declared','requested_only','request_observed','mismatch']),
  source_sha256: z.string(), candidate_file_sha256: z.string(), evidence_sha256: z.string().nullable().optional(),
  guide_version: z.string().nullable().optional(), guide_bundle_sha256: z.string().nullable().optional(),
  completed_at: z.string().nullable().optional(),
  outcome: z.enum(['completed','needs_revision','partial','failed','unknown']),
  applied_workspace_version: z.number().int().positive().nullable().optional(),
}).strict();
export type AiProvenanceRecord = z.infer<typeof aiProvenanceSchema>;
export const aiProvenanceListSchema = z.object({ items: z.array(aiProvenanceSchema), workspace_version: z.number().int().positive() }).strict();
export function getAiProvenance(workspaceId: string) {
  return apiRequest(`/api/v2/workspaces/${workspaceId}/ai-provenance`, aiProvenanceListSchema);
}

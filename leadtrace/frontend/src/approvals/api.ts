import { z } from "zod";

import { apiRequest } from "../api/client";
import { useAuthStore } from "../auth/store";

const approvalDecisionSchema = z.object({
  id: z.string().uuid(),
  changeset_id: z.string().uuid(),
  submission_version: z.number().int().positive(),
  decision: z.enum(["approve", "request_changes", "reject"]),
  actor_id: z.string().uuid(),
  reason: z.string(),
  snapshot: z.record(z.string(), z.unknown()),
  snapshot_hash: z.string().length(64),
  created_at: z.string(),
  idempotent: z.boolean().optional(),
  request_id: z.string().optional(),
});

export type ApprovalDecision = z.infer<typeof approvalDecisionSchema>;
export type ApprovalAction = "approve" | "request-changes" | "reject";

const scientificEvidenceEntrySchema = z.object({
  object_id: z.string().uuid(),
  before: z.record(z.string(), z.unknown()),
  after: z.record(z.string(), z.unknown()),
});

const scientificEvidenceSchema = z.object({
  changeset_id: z.string().uuid(),
  base_release_id: z.string().uuid(),
  submission_version: z.number().int().positive(),
  snapshot_hash: z.string().length(64),
  structures: scientificEvidenceEntrySchema.array(),
  regions: scientificEvidenceEntrySchema.array(),
});

export type ScientificEvidence = z.infer<typeof scientificEvidenceSchema>;

export function fetchApprovals(changesetId?: string): Promise<ApprovalDecision[]> {
  const query = changesetId
    ? `?changeset_id=${encodeURIComponent(changesetId)}`
    : "";
  return apiRequest(`/api/v1/approvals${query}`, approvalDecisionSchema.array());
}

export function fetchScientificEvidence(
  changesetId: string,
): Promise<ScientificEvidence> {
  return apiRequest(
    `/api/v1/approvals/${encodeURIComponent(changesetId)}/scientific-evidence`,
    scientificEvidenceSchema,
  );
}

export function decideApproval(
  changesetId: string,
  action: ApprovalAction,
  expectedVersion: number,
  reason: string,
): Promise<ApprovalDecision> {
  return apiRequest(
    `/api/v1/approvals/${encodeURIComponent(changesetId)}/${action}`,
    approvalDecisionSchema,
    {
      method: "POST",
      csrfToken: useAuthStore().csrfToken,
      body: { expected_version: expectedVersion, reason },
    },
  );
}

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

const evidenceAssetSchema = z.object({
  id: z.string().uuid(),
  url: z.string().startsWith("/api/v1/assets/").endsWith("/content"),
  original_filename: z.string(),
  sha256: z.string().length(64),
  byte_size: z.number().int().nonnegative(),
  mime_type: z.string(),
  width: z.number().int().positive().nullable(),
  height: z.number().int().positive().nullable(),
  page_count: z.number().int().positive().nullable(),
  category: z.string(),
  access_level: z.enum(["visitor", "reviewer", "admin"]),
}).strict();

const proposalEvidenceSchema = scientificEvidenceEntrySchema.extend({
  before_disposition: z.string(),
  after_disposition: z.string(),
}).strict();

const sourceContextSchema = z.object({
  proposal_id: z.string().uuid(),
  visual_object_id: z.string().uuid(),
  region: z.object({
    id: z.string().uuid(),
    page_number: z.number().int().positive(),
    bounds: z.object({
      x0: z.number(), y0: z.number(), x1: z.number(), y1: z.number(),
    }).strict(),
    rotation: z.number(),
  }).strict(),
  crop_asset: evidenceAssetSchema.nullable(),
  source_asset: evidenceAssetSchema.nullable(),
}).strict();

const scientificEvidenceSchema = z.object({
  changeset_id: z.string().uuid(),
  base_release_id: z.string().uuid(),
  submission_version: z.number().int().positive(),
  snapshot_hash: z.string().length(64),
  structures: scientificEvidenceEntrySchema.array(),
  regions: scientificEvidenceEntrySchema.array(),
  visual_objects: scientificEvidenceEntrySchema.array().optional(),
  molecule_proposals: proposalEvidenceSchema.array().optional(),
  source_context: sourceContextSchema.array().optional(),
  scope: z.record(z.string(), z.unknown()).nullable().optional(),
  attestation: z.record(z.string(), z.unknown()).nullable().optional(),
  progress: z.record(z.string(), z.unknown()).nullable().optional(),
}).strict();

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

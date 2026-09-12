import { z } from "zod";

import { apiRequest } from "../api/client";
import { useAuthStore } from "../auth/store";

export const adminReleaseSchema = z.object({
  id: z.string().uuid(),
  release_key: z.string(),
  title: z.string(),
  notes: z.string(),
  published_at: z.string(),
  is_current: z.boolean(),
  manifest_finalized: z.boolean(),
  metrics: z.record(z.string(), z.unknown()),
});

const operationSchema = z.object({
  release_id: z.string().uuid(),
  release_key: z.string(),
  validation: z.record(z.string(), z.unknown()),
  idempotent: z.boolean().optional(),
  operation_id: z.string().uuid().nullable().optional(),
  request_id: z.string().optional(),
});

export const releasePreviewSchema = z.object({
  changeset_id: z.string().uuid(),
  base_release_id: z.string().uuid(),
  counts: z.object({
    create: z.number().int().nonnegative(),
    update: z.number().int().nonnegative(),
    tombstone: z.number().int().nonnegative(),
    total: z.number().int().nonnegative(),
  }),
  by_object_kind: z.record(
    z.string(),
    z.object({
      create: z.number().int().nonnegative(),
      update: z.number().int().nonnegative(),
      tombstone: z.number().int().nonnegative(),
      total: z.number().int().nonnegative(),
    }),
  ),
  objects: z.array(z.record(z.string(), z.unknown())),
  affected_asset_ids: z.array(z.string().uuid()),
  validation: z.object({
    valid: z.boolean(),
    issues: z.array(z.object({
      code: z.string(),
      message: z.string(),
      object_id: z.string().uuid().nullable().optional(),
    })),
  }).passthrough(),
});

export type AdminRelease = z.infer<typeof adminReleaseSchema>;
export type ReleasePreview = z.infer<typeof releasePreviewSchema>;

export function createReleaseOperationKey(scope: "publish" | "rollback"): string {
  return `${scope}-${crypto.randomUUID()}`;
}

function csrfToken(): string | null {
  return useAuthStore().csrfToken;
}

export function fetchReleases(): Promise<AdminRelease[]> {
  return apiRequest("/api/v1/releases", adminReleaseSchema.array());
}

export function publishChangeset(input: {
  changeset_id: string;
  title?: string;
  notes: string;
}, idempotencyKey: string): Promise<z.infer<typeof operationSchema>> {
  return apiRequest("/api/v1/releases/publish", operationSchema, {
    method: "POST",
    csrfToken: csrfToken(),
    headers: { "Idempotency-Key": idempotencyKey },
    body: input,
  });
}

export function rollbackToRelease(
  targetReleaseId: string,
  reason: string,
  idempotencyKey: string,
): Promise<z.infer<typeof operationSchema>> {
  return apiRequest("/api/v1/releases/rollback", operationSchema, {
    method: "POST",
    csrfToken: csrfToken(),
    headers: { "Idempotency-Key": idempotencyKey },
    body: { target_release_id: targetReleaseId, reason },
  });
}

export function previewRelease(changesetId: string): Promise<ReleasePreview> {
  return apiRequest(
    `/api/v1/releases/preview/${encodeURIComponent(changesetId)}`,
    releasePreviewSchema,
  );
}

export function validateRelease(releaseId: string): Promise<Record<string, unknown>> {
  return apiRequest(
    `/api/v1/releases/${encodeURIComponent(releaseId)}/validation`,
    z.record(z.string(), z.unknown()),
  );
}

export function exportRelease(releaseId: string): Promise<Record<string, unknown>> {
  return apiRequest(
    `/api/v1/releases/${encodeURIComponent(releaseId)}/export`,
    z.record(z.string(), z.unknown()),
  );
}

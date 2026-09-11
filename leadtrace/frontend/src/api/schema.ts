import { z } from "zod";

export const roleSchema = z.enum(["visitor", "reviewer", "admin"]);

export const authUserSchema = z.object({
  username: z.string(),
  display_name: z.string(),
  role: roleSchema,
  must_change_password: z.boolean(),
});

export const authenticationResponseSchema = z.object({
  user: authUserSchema,
  csrf_token: z.string().min(1),
});

export const apiErrorSchema = z.object({
  code: z.string(),
  message: z.string(),
  details: z.record(z.string(), z.unknown()).default({}),
  request_id: z.string(),
});

export const releaseSchema = z.object({
  id: z.string().uuid(),
  key: z.string(),
  title: z.string(),
  published_at: z.string(),
});

export const metricSchema = z.object({
  numerator: z.number().int().nonnegative(),
  denominator: z.number().int().nonnegative(),
  unit: z.string(),
});

export const overviewSchema = z.object({
  request_id: z.string(),
  release: releaseSchema,
  metrics: z.object({
    corpus: metricSchema,
    lineage: metricSchema,
    relation: metricSchema,
    structure: metricSchema,
    pair: metricSchema,
    human_review: metricSchema,
  }),
});

export const paperSummarySchema = z.object({
  id: z.string().uuid(),
  revision_id: z.string().uuid(),
  paper_key: z.string(),
  doi: z.string().nullable(),
  title: z.string(),
  year: z.string().nullable(),
  target: z.string().nullable(),
  review_status: z.string().nullable(),
});

export const paperListSchema = z.object({
  request_id: z.string(),
  release: releaseSchema,
  pagination: z.object({
    page: z.number().int().positive(),
    page_size: z.number().int().positive(),
    total_items: z.number().int().nonnegative(),
    total_pages: z.number().int().nonnegative(),
  }),
  filters: z.record(z.string(), z.unknown()),
  items: z.array(paperSummarySchema),
});

export const compoundSchema = z.object({
  id: z.string().uuid(),
  revision_id: z.string().uuid(),
  local_identity: z.string(),
  label: z.string(),
});

export const lineageSchema = z.object({
  id: z.string().uuid(),
  revision_id: z.string().uuid(),
  lineage_key: z.string(),
});

export const lineageEdgeSchema = z.object({
  id: z.string().uuid(),
  revision_id: z.string().uuid(),
  lineage_id: z.string().uuid(),
  parent_compound_id: z.string().uuid().nullable(),
  derived_compound_id: z.string().uuid(),
  relation_type: z.string().nullable(),
  relation_status: z.string().nullable(),
  pair_ready: z.boolean(),
});

export const structureSchema = z.object({
  id: z.string().uuid(),
  revision_id: z.string().uuid(),
  compound_id: z.string().uuid(),
  state: z.string().nullable(),
  canonical_smiles: z.string().nullable(),
});

export const evidenceSchema = z.object({
  id: z.string().uuid(),
  revision_id: z.string().uuid(),
  state: z.string().nullable(),
  text: z.string().nullable(),
});

export const activitySchema = z.object({
  id: z.string().uuid(),
  revision_id: z.string().uuid(),
  compound_id: z.string().uuid(),
  state: z.string().nullable(),
  metric: z.string().nullable(),
  value: z.string().nullable(),
  unit: z.string().nullable(),
  qualifier: z.string().nullable(),
});

const qualityCountSchema = z.object({
  total: z.number().int().nonnegative(),
});

export const qualitySummarySchema = z.object({
  relations: qualityCountSchema.extend({ resolved: z.number().int().nonnegative() }),
  structures: qualityCountSchema.extend({ confirmed: z.number().int().nonnegative() }),
  pair_ready: qualityCountSchema.extend({ eligible: z.number().int().nonnegative() }),
  human_review: qualityCountSchema.extend({ reviewed: z.number().int().nonnegative() }),
});

export const paperDetailSchema = z.object({
  request_id: z.string(),
  release: releaseSchema,
  paper: paperSummarySchema,
  compounds: z.array(compoundSchema),
  lineages: z.array(lineageSchema),
  lineage_edges: z.array(lineageEdgeSchema),
  structures: z.array(structureSchema),
  evidence: z.array(evidenceSchema),
  activities: z.array(activitySchema),
  quality_summary: qualitySummarySchema,
});

export type UserRole = z.infer<typeof roleSchema>;
export type AuthUser = z.infer<typeof authUserSchema>;
export type AuthenticationResponse = z.infer<typeof authenticationResponseSchema>;
export type OverviewResponse = z.infer<typeof overviewSchema>;
export type PaperListResponse = z.infer<typeof paperListSchema>;
export type ReleaseMetadata = z.infer<typeof releaseSchema>;
export type PaperSummary = z.infer<typeof paperSummarySchema>;
export type PaperDetailResponse = z.infer<typeof paperDetailSchema>;
export type Compound = z.infer<typeof compoundSchema>;
export type Lineage = z.infer<typeof lineageSchema>;
export type LineageEdge = z.infer<typeof lineageEdgeSchema>;
export type Structure = z.infer<typeof structureSchema>;
export type Evidence = z.infer<typeof evidenceSchema>;
export type Activity = z.infer<typeof activitySchema>;
export type QualitySummary = z.infer<typeof qualitySummarySchema>;

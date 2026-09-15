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
  verification_status: z.enum(["unverified", "partially_verified", "human_verified"]),
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
  drawing_asset: z.object({
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
    access_level: z.literal("visitor"),
  }).strict().nullable().optional(),
}).strict();

const publishedAssetSchema = z.object({
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
  access_level: z.literal("visitor"),
}).strict();

const publishedRegionSchema = z.object({
  id: z.string().uuid(),
  region_key: z.string(),
  revision_id: z.string().uuid(),
  page_number: z.number().int().positive(),
  bounds: z.object({ x0: z.number(), y0: z.number(), x1: z.number(), y1: z.number() }).strict(),
  rotation: z.number(),
  asset: publishedAssetSchema.nullable(),
}).strict();

const publishedVisualObjectSchema = z.object({
  id: z.string().uuid(),
  object_key: z.string(),
  object_type: z.string(),
  revision_id: z.string().uuid(),
  snapshot: z.record(z.string(), z.unknown()),
  region_id: z.string().uuid().nullable(),
}).strict();

const publishedProposalSchema = z.object({
  id: z.string().uuid(),
  visual_object_id: z.string().uuid(),
  proposal_key: z.string(),
  model_run_key: z.string(),
  revision_id: z.string().uuid(),
  disposition: z.string(),
  machine: z.object({ raw_values: z.record(z.string(), z.unknown()), normalized_values: z.record(z.string(), z.unknown()) }).strict(),
  review: z.record(z.string(), z.unknown()),
  crop_asset: publishedAssetSchema.nullable(),
  source_region_id: z.string().uuid().nullable(),
}).strict();

const publishedSourceLocatorSchema = z.object({
  proposal_id: z.string().uuid(),
  visual_object_id: z.string().uuid(),
  region: z.object({
    id: z.string().uuid(),
    page_number: z.number().int().positive(),
    bounds: z.object({ x0: z.number(), y0: z.number(), x1: z.number(), y1: z.number() }).strict(),
    rotation: z.number(),
  }).strict(),
  crop_asset: publishedAssetSchema.nullable(),
  source_asset: publishedAssetSchema.nullable(),
}).strict();

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

export const reviewTaskStatusSchema = z.enum([
  "open",
  "in_progress",
  "submitted",
  "changes_requested",
  "completed",
]);

export const workflowStateSchema = z.enum([
  "draft",
  "revised_draft",
  "submitted",
  "changes_requested",
  "approved",
  "published",
  "superseded",
  "rejected",
]);

export const reviewTaskSchema = z.object({
  id: z.string().uuid(),
  paper_id: z.string().uuid(),
  assigned_reviewer_id: z.string().uuid(),
  created_by_id: z.string().uuid(),
  status: reviewTaskStatusSchema,
  priority: z.number().int().nonnegative(),
  version: z.number().int().positive(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const changesetSchema = z.object({
  id: z.string().uuid(),
  review_task_id: z.string().uuid(),
  paper_id: z.string().uuid(),
  owner_id: z.string().uuid(),
  base_release_id: z.string().uuid(),
  title: z.string(),
  reason: z.string(),
  workflow_state: workflowStateSchema,
  version: z.number().int().positive(),
  validation_results: z.record(z.string(), z.unknown()),
  submitted_snapshot: z.record(z.string(), z.unknown()).nullable(),
  submitted_content_hash: z.string().length(64).nullable(),
  submitted_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const changesetItemSchema = z.object({
  id: z.string().uuid(),
  changeset_id: z.string().uuid(),
  paper_id: z.string().uuid(),
  object_id: z.string().uuid(),
  object_kind: z.enum([
    "paper",
    "compound",
    "structure",
    "evidence",
    "activity",
    "lineage",
    "lineage_edge",
    "visual_region",
    "visual_object",
    "molecule_proposal",
  ]),
  base_revision_id: z.string().uuid().nullable(),
  proposed_revision_id: z.string().uuid().nullable(),
  proposed_snapshot: z.record(z.string(), z.unknown()),
  content_hash: z.string().length(64),
  sequence: z.number().int().positive(),
  changeset_version: z.number().int().positive(),
  created_at: z.string(),
});

export const changesetMutationSchema = z.object({
  changeset_id: z.string().uuid(),
  version: z.number().int().positive(),
});

export const revisionChangeSchema = z.object({
  path: z.string(),
  category: z.string(),
  before_present: z.boolean(),
  after_present: z.boolean(),
  before: z.unknown().nullable(),
  after: z.unknown().nullable(),
});

export const revisionDiffSchema = z.object({
  object_id: z.string().uuid(),
  object_kind: z.string(),
  base_revision_id: z.string().uuid().nullable(),
  proposed_revision_id: z.string().uuid().nullable(),
  change_type: z.enum(["no_change", "create", "update", "tombstone"]),
  changes: z.array(revisionChangeSchema),
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
  regions: publishedRegionSchema.array().optional(),
  visual_objects: publishedVisualObjectSchema.array().optional(),
  molecule_proposals: publishedProposalSchema.array().optional(),
  source_locators: publishedSourceLocatorSchema.array().optional(),
  verification: z.object({
    ai_baseline: z.string(),
    human_verified: z.boolean(),
    release_status: z.enum(["unverified", "partially_verified", "human_verified"]),
  }).strict().optional(),
  review_entry: z.object({ href: z.string(), label: z.string() }).strict().nullable().optional(),
}).strict();

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
export type ReviewTaskStatus = z.infer<typeof reviewTaskStatusSchema>;
export type WorkflowState = z.infer<typeof workflowStateSchema>;
export type ReviewTask = z.infer<typeof reviewTaskSchema>;
export type Changeset = z.infer<typeof changesetSchema>;
export type ChangesetItem = z.infer<typeof changesetItemSchema>;
export type ChangesetMutation = z.infer<typeof changesetMutationSchema>;
export type RevisionDiff = z.infer<typeof revisionDiffSchema>;

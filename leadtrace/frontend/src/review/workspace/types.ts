import { z } from "zod";

import { workflowStateSchema } from "../../api/schema";

export const queueStateSchema = z.enum([
  "localization_or_split",
  "needs_ocsr",
  "proposal_review",
  "source_or_attachment",
  "structure_assembly",
  "complete",
]);

export const moleculeObjectTypeSchema = z.enum([
  "complete_molecule",
  "shared_scaffold",
  "r_group",
  "linker",
  "variable_site",
  "replacement_fragment",
  "multi_structure_region",
  "reaction_or_scheme_context",
  "mixed_chemical_region",
  "non_structure",
  "uncertain",
]);

export const moleculeProposalDispositionSchema = z.enum([
  "pending",
  "accepted",
  "corrected",
  "rejected",
  "not_applicable",
]);

const objectKindSchema = z.enum([
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
]);

const assetCategorySchema = z.enum([
  "article_pdf",
  "si_pdf",
  "si_table",
  "si_archive",
  "external_source",
  "page_render",
  "page_thumbnail",
  "evidence_crop",
  "ocsr_input",
  "ocsr_proposal",
  "reviewed_crop",
  "rdkit_structure",
  "pair_panel",
  "import_manifest",
  "validation_report",
  "release_export",
  "upload_staging",
  "render_cache",
  "quarantine",
]);

function forbiddenPath(value: unknown): string | undefined {
  if (Array.isArray(value)) {
    for (const item of value) {
      const nested = forbiddenPath(item);
      if (nested) return nested;
    }
    return undefined;
  }
  if (value === null || typeof value !== "object") return undefined;
  for (const [key, nestedValue] of Object.entries(value)) {
    const normalized = key.toLocaleLowerCase();
    if (
      ["storage_key", "source_pdf", "crop_path", "source_crop_path"].includes(normalized)
      || normalized.endsWith("_path")
      || normalized.endsWith("_filepath")
    ) return key;
    const nested = forbiddenPath(nestedValue);
    if (nested) return `${key}.${nested}`;
  }
  return undefined;
}

const safeRecordSchema = z.record(z.string(), z.unknown()).superRefine((value, context) => {
  const path = forbiddenPath(value);
  if (path) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: `Filesystem path field is forbidden: ${path}`,
    });
  }
});

export const workspaceAssetSchema = z.object({
  id: z.string().uuid(),
  url: z.string().startsWith("/api/v1/assets/").endsWith("/content"),
  original_filename: z.string(),
  sha256: z.string().length(64),
  byte_size: z.number().int().nonnegative(),
  mime_type: z.string(),
  width: z.number().int().positive().nullable(),
  height: z.number().int().positive().nullable(),
  page_count: z.number().int().positive().nullable(),
  category: assetCategorySchema,
  access_level: z.enum(["visitor", "reviewer", "admin"]),
}).strict().superRefine((value, context) => {
  if (value.url !== `/api/v1/assets/${value.id}/content`) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Asset URL does not match its ID",
      path: ["url"],
    });
  }
});

export const regionBoundsSchema = z.object({
  x0: z.number().min(0).max(1),
  y0: z.number().min(0).max(1),
  x1: z.number().min(0).max(1),
  y1: z.number().min(0).max(1),
}).strict().superRefine((value, context) => {
  if (value.x0 >= value.x1) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "x0 must be less than x1",
      path: ["x1"],
    });
  }
  if (value.y0 >= value.y1) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "y0 must be less than y1",
      path: ["y1"],
    });
  }
});

const progressSummaryShape = {
  scope_count: z.number().int().nonnegative(),
  resolved_count: z.number().int().nonnegative(),
  blocker_count: z.number().int().nonnegative(),
};

function validateProgress(
  value: { scope_count: number; resolved_count: number; blocker_count: number },
  context: z.RefinementCtx,
): void {
  if (value.resolved_count > value.scope_count) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Resolved count exceeds scope",
      path: ["resolved_count"],
    });
  }
  if (value.blocker_count > value.scope_count) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Blocker count exceeds scope",
      path: ["blocker_count"],
    });
  }
}

const progressSummarySchema = z.object(progressSummaryShape)
  .strict()
  .superRefine(validateProgress);

const progressKindSchema = z.object({
  total: z.number().int().nonnegative(),
  resolved: z.number().int().nonnegative(),
  blockers: z.number().int().nonnegative(),
}).strict();

const progressSchema = z.object({
  ...progressSummaryShape,
  by_kind: z.record(objectKindSchema, progressKindSchema),
}).strict().superRefine(validateProgress);

const changesetProjectionSchema = z.object({
  id: z.string().uuid(),
  review_task_id: z.string().uuid(),
  paper_id: z.string().uuid(),
  owner_id: z.string().uuid(),
  base_release_id: z.string().uuid(),
  workflow_state: workflowStateSchema,
  version: z.number().int().positive(),
  title: z.string(),
  reason: z.string(),
}).strict();

const paperProjectionSchema = z.object({
  id: z.string().uuid(),
  paper_key: z.string(),
  title: z.string().nullable(),
  base_release_id: z.string().uuid(),
}).strict();

const regionSchema = z.object({
  id: z.string().uuid(),
  region_key: z.string(),
  revision_id: z.string().uuid(),
  page_number: z.number().int().positive(),
  bounds: regionBoundsSchema,
  rotation: z.union([z.literal(0), z.literal(90), z.literal(180), z.literal(270)]),
  asset_id: z.string().uuid().nullable(),
  asset: workspaceAssetSchema.nullable(),
}).strict();

const visualObjectSchema = z.object({
  id: z.string().uuid(),
  object_key: z.string(),
  object_type: moleculeObjectTypeSchema,
  revision_id: z.string().uuid(),
  snapshot: safeRecordSchema,
  queue_state: queueStateSchema,
  blocking: z.boolean(),
  region_id: z.string().uuid().nullable(),
  bindings: z.object({
    regions: safeRecordSchema.array(),
    assets: safeRecordSchema.array(),
    compounds: safeRecordSchema.array(),
    relations: safeRecordSchema.array(),
  }).strict(),
}).strict();

const workspaceProposalSchema = z.object({
  id: z.string().uuid(),
  paper_id: z.string().uuid(),
  visual_object_id: z.string().uuid(),
  proposal_key: z.string(),
  model_run_key: z.string(),
  revision_id: z.string().uuid(),
  disposition: moleculeProposalDispositionSchema,
  machine: z.object({
    raw_values: safeRecordSchema,
    normalized_values: safeRecordSchema,
  }).strict(),
  review: safeRecordSchema,
  crop_asset: workspaceAssetSchema.nullable(),
  source_region_id: z.string().uuid().nullable(),
}).strict();

const structureStateSchema = z.enum([
  "proposal",
  "parseable_candidate",
  "source_bound_candidate",
  "structure_confirmed",
  "constitution_confirmed",
  "non_unique_stereochemistry",
  "multicomponent_unresolved",
  "source_structure_mismatch",
  "rejected",
]);

const structureSchema = z.object({
  id: z.string().uuid(),
  compound_id: z.string().uuid(),
  structure_key: z.string(),
  revision_id: z.string().uuid(),
  state: structureStateSchema.nullable(),
  canonical_smiles: z.string().nullable(),
  snapshot: safeRecordSchema,
}).strict();

const sourceLocatorSchema = z.object({
  visual_object_id: z.string().uuid(),
  region_id: z.string().uuid(),
  page_number: z.number().int().positive(),
  bounds: regionBoundsSchema,
  source_asset_id: z.string().uuid().nullable(),
  crop_asset_id: z.string().uuid().nullable(),
}).strict();

export const workspaceAttestationSchema = z.object({
  id: z.string().uuid(),
  changeset_version: z.number().int().positive(),
  scope_hash: z.string().length(64),
  item_count: z.number().int().nonnegative(),
  resolved_count: z.number().int().nonnegative(),
  blocker_count: z.number().int().nonnegative(),
  statement: z.string(),
}).strict();

export const workspaceSchema = z.object({
  workspace_version: z.number().int().positive(),
  changeset: changesetProjectionSchema,
  paper: paperProjectionSchema,
  progress: progressSchema,
  document: z.object({
    url: z.string().startsWith("/api/v1/papers/"),
    release_id: z.string().uuid(),
  }).strict(),
  pages: z.object({
    page_number: z.number().int().positive(),
    region_count: z.number().int().nonnegative(),
    visual_object_count: z.number().int().nonnegative(),
    proposal_count: z.number().int().nonnegative(),
    blocker_count: z.number().int().nonnegative(),
  }).strict().array(),
  regions: regionSchema.array(),
  visual_objects: visualObjectSchema.array(),
  molecule_proposals: workspaceProposalSchema.array(),
  structures: structureSchema.array(),
  evidence: safeRecordSchema.array(),
  assets: workspaceAssetSchema.array(),
  source_locators: sourceLocatorSchema.array(),
  attestation: workspaceAttestationSchema.nullable(),
  scope: z.object({
    id: z.string().uuid(),
    scope_hash: z.string().length(64),
    item_count: z.number().int().nonnegative(),
  }).strict(),
}).strict().superRefine((value, context) => {
  const expectedPaperId = value.paper.id;
  const regionIds = new Set(value.regions.map((region) => region.id));
  const visualIds = new Set(value.visual_objects.map((visual) => visual.id));
  if (
    value.changeset.paper_id !== expectedPaperId
    || value.changeset.base_release_id !== value.paper.base_release_id
    || value.document.release_id !== value.paper.base_release_id
  ) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Workspace Paper or Release scope is inconsistent",
      path: ["paper"],
    });
  }
  if (value.workspace_version !== value.changeset.version) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Workspace version is inconsistent",
      path: ["workspace_version"],
    });
  }
  value.visual_objects.forEach((visual, index) => {
    if (visual.region_id && !regionIds.has(visual.region_id)) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Visual Object references an unknown Region",
        path: ["visual_objects", index, "region_id"],
      });
    }
  });
  value.molecule_proposals.forEach((proposal, index) => {
    if (
      proposal.paper_id !== expectedPaperId
      || !visualIds.has(proposal.visual_object_id)
      || (proposal.source_region_id && !regionIds.has(proposal.source_region_id))
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Molecule proposal crosses workspace scope",
        path: ["molecule_proposals", index],
      });
    }
  });
});

const queueVisualObjectSchema = z.object({
  id: z.string().uuid(),
  object_key: z.string(),
  object_type: moleculeObjectTypeSchema,
  region_id: z.string().uuid(),
}).strict();

const queueProposalSchema = z.object({
  id: z.string().uuid(),
  proposal_key: z.string(),
  disposition: moleculeProposalDispositionSchema,
  revision_id: z.string().uuid().nullable(),
}).strict();

export const moleculeObjectQueueSchema = z.object({
  items: z.object({
    paper_id: z.string().uuid(),
    paper_key: z.string(),
    base_release_id: z.string().uuid(),
    review_task_id: z.string().uuid(),
    changeset_id: z.string().uuid().nullable(),
    changeset_version: z.number().int().positive().nullable(),
    visual_object: queueVisualObjectSchema,
    proposal: queueProposalSchema.nullable(),
    crop_asset: workspaceAssetSchema.nullable(),
    page: z.number().int().positive(),
    state: queueStateSchema,
    blocking: z.boolean(),
    reasons: z.string().array(),
    paper_progress: progressSummarySchema,
    deep_link: z.object({
      view: z.literal("ocsr"),
      page: z.number().int().positive(),
      object: z.string().uuid(),
      proposal: z.string().uuid().nullable(),
    }).strict(),
    priority: z.number().int().nonnegative(),
  }).strict().array(),
  next_cursor: z.string().nullable(),
  status_counts: z.object({
    localization_or_split: z.number().int().nonnegative(),
    needs_ocsr: z.number().int().nonnegative(),
    proposal_review: z.number().int().nonnegative(),
    source_or_attachment: z.number().int().nonnegative(),
    structure_assembly: z.number().int().nonnegative(),
    complete: z.number().int().nonnegative(),
  }).strict(),
  pagination: z.object({
    limit: z.number().int().min(1).max(100),
    returned: z.number().int().nonnegative(),
  }).strict(),
}).strict();

export const moleculeProposalSchema = workspaceProposalSchema.extend({
  revision_number: z.number().int().positive(),
  changeset_id: z.string().uuid().nullable(),
  changeset_version: z.number().int().positive().nullable(),
  source_region_id: z.never().optional(),
  source_region: safeRecordSchema.nullable(),
}).strict();

export const paperAttestationSchema = z.object({
  id: z.string().uuid(),
  changeset_id: z.string().uuid(),
  paper_id: z.string().uuid(),
  changeset_version: z.number().int().positive(),
  scope_hash: z.string().length(64),
  item_count: z.number().int().nonnegative(),
  resolved_count: z.number().int().nonnegative(),
  blocker_count: z.number().int().nonnegative(),
  statement: z.string(),
  stale: z.boolean(),
}).strict();

export type QueueState = z.infer<typeof queueStateSchema>;
export type MoleculeObjectType = z.infer<typeof moleculeObjectTypeSchema>;
export type MoleculeProposalDisposition = z.infer<typeof moleculeProposalDispositionSchema>;
export type WorkspaceAsset = z.infer<typeof workspaceAssetSchema>;
export type RegionBounds = z.infer<typeof regionBoundsSchema>;
export type Workspace = z.infer<typeof workspaceSchema>;
export type WorkspaceRegion = Workspace["regions"][number];
export type WorkspaceVisualObject = Workspace["visual_objects"][number];
export type WorkspaceMoleculeProposal = Workspace["molecule_proposals"][number];
export type WorkspaceStructure = Workspace["structures"][number];
export type MoleculeObjectQueue = z.infer<typeof moleculeObjectQueueSchema>;
export type MoleculeObjectQueueItem = MoleculeObjectQueue["items"][number];
export type MoleculeProposal = z.infer<typeof moleculeProposalSchema>;
export type PaperAttestation = z.infer<typeof paperAttestationSchema>;

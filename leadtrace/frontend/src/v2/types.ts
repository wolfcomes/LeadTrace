import { z } from "zod";


const uuidSchema = z.string().uuid();
const sha256Schema = z.string().regex(/^[0-9a-f]{64}$/);
const timestampSchema = z.string().datetime({ offset: true });
const decimalSchema = z.union([
  z.number().finite(),
  z.string().regex(/^-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/),
]);

export const sourceRootKeySchema = z.string()
  .min(1)
  .max(128)
  .regex(/^[A-Za-z0-9][A-Za-z0-9._-]*$/)
  .refine((value) => value !== "." && value !== "..", "Source root must be logical");

export const sourceKeySchema = z.string().min(1).max(1024).superRefine((value, context) => {
  const unsafe = value.startsWith("/")
    || value.startsWith("\\")
    || /^[A-Za-z]:[\\/]/.test(value)
    || /^[a-z][a-z0-9+.-]*:\/\//i.test(value)
    || value.includes("\\")
    || value.endsWith("/")
    || value.includes("//")
    || value.split("/").some((part) => part === "." || part === "..");
  if (unsafe) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Source key must be a safe project-relative POSIX path",
    });
  }
});

export const paperCatalogStateSchema = z.enum(["extracted", "verified", "source_error"]);
export const sourceIntegrityStateSchema = z.enum([
  "registered",
  "verified",
  "missing",
  "corrupt",
]);
export const reviewTaskStateSchema = z.enum([
  "assigned",
  "submitted",
  "changes_requested",
  "approved",
]);
export const workspaceStateSchema = z.enum(["editing", "submitted", "approved"]);
export const sectionKeySchema = z.enum([
  "bibliography",
  "compounds",
  "structures",
  "lineages",
  "edge_evidence",
  "activities",
]);
export const sectionStateSchema = z.enum(["pending", "completed", "not_reported"]);
export const actorKindSchema = z.enum(["reviewer", "admin", "ai", "system"]);
export const structureStatusSchema = z.enum([
  "draft",
  "reviewer_confirmed",
  "unresolved",
  "not_reported",
]);
export const structureInputMethodSchema = z.enum([
  "ai_prefill",
  "manual_smiles",
  "structure_editor",
]);
export const cropStatusSchema = z.enum(["pending", "ready", "failed"]);
export const lineageMemberRoleSchema = z.enum([
  "root",
  "intermediate",
  "terminal",
  "unspecified",
]);
export const lineageEdgeReviewStatusSchema = z.enum([
  "draft",
  "reviewer_confirmed",
  "unresolved",
]);
export const evidenceKindSchema = z.enum(["text", "table", "scheme", "image"]);
export const evidenceRoleSchema = z.enum(["supports", "contradicts", "contextual"]);
export const activityOperatorSchema = z.enum(["=", "<", "<=", ">", ">=", "~"]);
export const adminDecisionActionSchema = z.enum(["approve", "request_changes"]);

const sectionSchema = z.object({
  section_key: sectionKeySchema,
  state: sectionStateSchema,
  note: z.string().nullable(),
}).strict();

const publishedSectionSchema = sectionSchema.omit({ note: true }).strict();
const requiredSections = new Set(sectionKeySchema.options);

function addSectionIssues(
  values: readonly { section_key: z.infer<typeof sectionKeySchema> }[],
  context: z.RefinementCtx,
): void {
  const present = new Set(values.map((value) => value.section_key));
  if (values.length !== requiredSections.size || present.size !== requiredSections.size) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "All six fixed sections must appear exactly once",
    });
    return;
  }
  for (const section of requiredSections) {
    if (!present.has(section)) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: `Missing fixed section: ${section}`,
      });
    }
  }
}

const sectionListSchema = z.array(sectionSchema).superRefine(addSectionIssues);
const publishedSectionListSchema = z.array(publishedSectionSchema).superRefine(addSectionIssues);

function workflowPairIsValid(
  workspaceState: z.infer<typeof workspaceStateSchema>,
  taskState: z.infer<typeof reviewTaskStateSchema>,
): boolean {
  return (workspaceState === "editing"
      && (taskState === "assigned" || taskState === "changes_requested"))
    || (workspaceState === "submitted" && taskState === "submitted")
    || (workspaceState === "approved" && taskState === "approved");
}

function addWorkflowPairIssue(
  value: {
    workspace_state?: z.infer<typeof workspaceStateSchema>;
    state?: z.infer<typeof workspaceStateSchema>;
    task_status: z.infer<typeof reviewTaskStateSchema>;
  },
  context: z.RefinementCtx,
): void {
  const workspaceState = value.workspace_state ?? value.state;
  if (workspaceState && !workflowPairIsValid(workspaceState, value.task_status)) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Workspace and Review Task states are inconsistent",
    });
  }
}

export const paperSourceSchema = z.object({
  id: uuidSchema,
  asset_id: uuidSchema,
  source_root_key: sourceRootKeySchema,
  source_key: sourceKeySchema,
  sha256: sha256Schema,
  byte_size: z.number().int().positive(),
  page_count: z.number().int().positive(),
  integrity_state: sourceIntegrityStateSchema,
}).strict();

export const paperCatalogRowSchema = z.object({
  id: uuidSchema,
  paper_key: z.string().min(1),
  title: z.string().min(1),
  journal: z.string().min(1),
  publication_year: z.number().int().min(1000).max(9999),
  volume: z.string().min(1),
  issue: z.string().min(1),
  doi: z.string().min(1).nullable(),
  catalog_state: paperCatalogStateSchema,
  source: paperSourceSchema,
}).strict();

export const paperCatalogPageSchema = z.object({
  items: z.array(paperCatalogRowSchema),
  total: z.number().int().nonnegative(),
  limit: z.number().int().min(1).max(500),
  offset: z.number().int().nonnegative(),
}).strict().superRefine((value, context) => {
  if (value.items.length > value.limit) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Catalog pagination is inconsistent" });
  }
});

export const reviewTaskSchema = z.object({
  review_task_id: uuidSchema,
  workspace_id: uuidSchema,
  paper_id: uuidSchema,
  paper_key: z.string().min(1),
  title: z.string().min(1),
  task_status: reviewTaskStateSchema,
  task_version: z.number().int().positive(),
  workspace_state: workspaceStateSchema,
  workspace_version: z.number().int().positive(),
}).strict().superRefine(addWorkflowPairIssue);

export const reviewTaskListSchema = z.object({
  items: z.array(reviewTaskSchema),
  total: z.number().int().nonnegative(),
}).strict().superRefine((value, context) => {
  if (value.items.length !== value.total) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Task total is inconsistent" });
  }
});

export const bibliographySchema = z.object({
  paper_id: uuidSchema,
  paper_key: z.string().min(1),
  title: z.string().min(1),
  journal: z.string().min(1),
  publication_year: z.number().int().min(1000).max(9999),
  volume: z.string().min(1),
  issue: z.string().min(1),
  doi: z.string().min(1).nullable(),
}).strict();

export const workspaceSourceSchema = z.object({
  asset_id: uuidSchema,
  source_root_key: sourceRootKeySchema,
  source_key: sourceKeySchema,
}).strict();

export const paperWorkspaceSchema = z.object({
  id: uuidSchema,
  review_task_id: uuidSchema,
  assigned_reviewer_id: uuidSchema,
  state: workspaceStateSchema,
  version: z.number().int().positive(),
  task_status: reviewTaskStateSchema,
  bibliography: bibliographySchema,
  source: workspaceSourceSchema,
  sections: sectionListSchema,
}).strict().superRefine(addWorkflowPairIssue);

export const changeEventSchema = z.object({
  id: uuidSchema,
  paper_id: uuidSchema,
  workspace_id: uuidSchema,
  entity_type: z.string().min(1),
  entity_id: uuidSchema,
  action: z.string().min(1),
  before_value: z.record(z.string(), z.unknown()).nullable(),
  after_value: z.record(z.string(), z.unknown()).nullable(),
  actor_kind: actorKindSchema,
  actor_id: uuidSchema.nullable(),
  ai_run_id: uuidSchema.nullable(),
  occurred_at: timestampSchema,
}).strict().superRefine((value, context) => {
  const human = value.actor_kind === "reviewer" || value.actor_kind === "admin";
  if (human !== (value.actor_id !== null)) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Human Change Events require an actor; AI/system events must not have one",
    });
  }
});

const snapshotPaperSchema = z.object({
  id: uuidSchema,
  paper_key: z.string().min(1),
  title: z.string().min(1),
  journal: z.string().min(1),
  publication_year: z.number().int().min(1000).max(9999),
  volume: z.string().min(1),
  issue: z.string().min(1),
  doi: z.string().min(1).nullable(),
  catalog_state: paperCatalogStateSchema,
}).strict();

const snapshotSourceSchema = workspaceSourceSchema.extend({
  sha256: sha256Schema,
  page_count: z.number().int().positive(),
}).strict();

const compoundSchema = z.object({
  id: uuidSchema,
  paper_id: uuidSchema,
  workspace_id: uuidSchema,
  compound_label: z.string().min(1),
  display_name: z.string().nullable(),
  description: z.string().nullable(),
  sort_order: z.number().int(),
  created_by_kind: actorKindSchema,
}).strict();

const structureSchema = z.object({
  id: uuidSchema,
  paper_id: uuidSchema,
  workspace_id: uuidSchema,
  compound_id: uuidSchema,
  smiles: z.string().nullable(),
  canonical_smiles: z.string().nullable(),
  molfile: z.string().nullable(),
  inchi: z.string().nullable(),
  inchikey: z.string().nullable(),
  depiction_asset_id: uuidSchema.nullable(),
  status: structureStatusSchema,
  input_method: structureInputMethodSchema,
}).strict();

const structureSourceImageSchema = z.object({
  id: uuidSchema,
  paper_id: uuidSchema,
  workspace_id: uuidSchema,
  compound_id: uuidSchema,
  source_sha256: sha256Schema,
  page_number: z.number().int().positive(),
  x0: decimalSchema,
  y0: decimalSchema,
  x1: decimalSchema,
  y1: decimalSchema,
  source_context: z.string().nullable(),
  label: z.string().nullable(),
  reviewer_note: z.string().nullable(),
  crop_status: cropStatusSchema,
  crop_asset_id: uuidSchema.nullable(),
}).strict();

const lineageSchema = z.object({
  id: uuidSchema,
  paper_id: uuidSchema,
  workspace_id: uuidSchema,
  lineage_label: z.string().min(1),
  description: z.string().nullable(),
  sort_order: z.number().int(),
}).strict();

const lineageMemberSchema = z.object({
  id: uuidSchema,
  paper_id: uuidSchema,
  workspace_id: uuidSchema,
  lineage_id: uuidSchema,
  compound_id: uuidSchema,
  role: lineageMemberRoleSchema,
  sort_order: z.number().int(),
}).strict();

const lineageEdgeSchema = z.object({
  id: uuidSchema,
  paper_id: uuidSchema,
  workspace_id: uuidSchema,
  lineage_id: uuidSchema,
  parent_compound_id: uuidSchema,
  child_compound_id: uuidSchema,
  relation_type: z.string().min(1),
  modification_summary: z.string().nullable(),
  review_status: lineageEdgeReviewStatusSchema,
  sort_order: z.number().int(),
}).strict();

const evidenceSchema = z.object({
  id: uuidSchema,
  paper_id: uuidSchema,
  workspace_id: uuidSchema,
  kind: evidenceKindSchema,
  source_sha256: sha256Schema,
  page_number: z.number().int().positive(),
  x0: decimalSchema.nullable(),
  y0: decimalSchema.nullable(),
  x1: decimalSchema.nullable(),
  y1: decimalSchema.nullable(),
  quoted_text: z.string().nullable(),
  caption: z.string().nullable(),
  crop_asset_id: uuidSchema.nullable(),
  reviewer_note: z.string().nullable(),
}).strict();

const edgeEvidenceLinkSchema = z.object({
  id: uuidSchema,
  paper_id: uuidSchema,
  workspace_id: uuidSchema,
  edge_id: uuidSchema,
  evidence_id: uuidSchema,
  role: evidenceRoleSchema,
}).strict();

const activitySchema = z.object({
  id: uuidSchema,
  paper_id: uuidSchema,
  workspace_id: uuidSchema,
  compound_id: uuidSchema,
  evidence_id: uuidSchema.nullable(),
  assay_name: z.string().min(1),
  metric: z.string().min(1),
  operator: activityOperatorSchema,
  value: decimalSchema,
  unit: z.string().nullable(),
  context: z.string().nullable(),
  sort_order: z.number().int(),
}).strict();

export const frozenPaperSnapshotSchema = z.object({
  schema_version: z.literal(1),
  paper: snapshotPaperSchema,
  source: snapshotSourceSchema,
  workspace_version: z.number().int().positive(),
  sections: sectionListSchema,
  compounds: z.array(compoundSchema),
  structures: z.array(structureSchema),
  structure_source_images: z.array(structureSourceImageSchema),
  lineages: z.array(lineageSchema),
  lineage_members: z.array(lineageMemberSchema),
  lineage_edges: z.array(lineageEdgeSchema),
  evidence: z.array(evidenceSchema),
  edge_evidence_links: z.array(edgeEvidenceLinkSchema),
  activities: z.array(activitySchema),
}).strict();

export const paperSubmissionSchema = z.object({
  id: uuidSchema,
  paper_id: uuidSchema,
  workspace_id: uuidSchema,
  review_task_id: uuidSchema,
  submission_number: z.number().int().positive(),
  idempotency_key: z.string().min(1).max(255),
  snapshot: frozenPaperSnapshotSchema,
  content_hash: sha256Schema,
  workspace_version: z.number().int().positive(),
  submitted_by_id: uuidSchema,
  reviewer_note: z.string().nullable(),
  submitted_at: timestampSchema,
}).strict().superRefine((value, context) => {
  if (value.snapshot.paper.id !== value.paper_id) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Submission Paper identity mismatch" });
  }
  if (value.snapshot.workspace_version !== value.workspace_version) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Submission Workspace version mismatch" });
  }
  const aggregateRows = [
    ...value.snapshot.compounds,
    ...value.snapshot.structures,
    ...value.snapshot.structure_source_images,
    ...value.snapshot.lineages,
    ...value.snapshot.lineage_members,
    ...value.snapshot.lineage_edges,
    ...value.snapshot.evidence,
    ...value.snapshot.edge_evidence_links,
    ...value.snapshot.activities,
  ];
  if (aggregateRows.some((row) => row.paper_id !== value.paper_id
    || row.workspace_id !== value.workspace_id)) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Submission contains a cross-Paper record" });
  }
});

export const adminSubmissionListItemSchema = z.object({
  submission_id: uuidSchema,
  paper_id: uuidSchema,
  workspace_id: uuidSchema,
  submission_number: z.number().int().positive(),
  content_hash: sha256Schema,
  submitted_by_id: uuidSchema,
  submitted_at: timestampSchema,
  paper_key: z.string().min(1),
  title: z.string().min(1),
}).strict();

export const adminSubmissionListSchema = z.object({
  items: z.array(adminSubmissionListItemSchema),
  total: z.number().int().nonnegative(),
}).strict().superRefine((value, context) => {
  if (value.items.length !== value.total) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Submission total is inconsistent" });
  }
});

export const adminSubmissionDetailSchema = z.object({
  submission: paperSubmissionSchema,
  bibliography: bibliographySchema,
  change_events: z.array(changeEventSchema),
  reviewer_diff: z.array(changeEventSchema),
}).strict().superRefine((value, context) => {
  const { paper_id: paperId, workspace_id: workspaceId } = value.submission;
  if (value.bibliography.paper_id !== paperId
    || [...value.change_events, ...value.reviewer_diff].some(
      (event) => event.paper_id !== paperId || event.workspace_id !== workspaceId,
    )) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Submission review identity mismatch" });
  }
});

const publishedPaperSchema = snapshotPaperSchema.omit({ catalog_state: true }).strict();
const publishedSourceSchema = z.object({
  sha256: sha256Schema,
  page_count: z.number().int().positive(),
}).strict();
const publishedCompoundSchema = compoundSchema.omit({
  paper_id: true,
  workspace_id: true,
  created_by_kind: true,
}).strict();
const publishedStructureSchema = structureSchema.omit({
  paper_id: true,
  workspace_id: true,
}).strict();
const publishedStructureSourceImageSchema = structureSourceImageSchema.omit({
  paper_id: true,
  workspace_id: true,
  reviewer_note: true,
}).strict();
const publishedLineageSchema = lineageSchema.omit({ paper_id: true, workspace_id: true }).strict();
const publishedLineageMemberSchema = lineageMemberSchema.omit({
  paper_id: true,
  workspace_id: true,
}).strict();
const publishedLineageEdgeSchema = lineageEdgeSchema.omit({
  paper_id: true,
  workspace_id: true,
}).strict();
const publishedEvidenceSchema = evidenceSchema.omit({
  paper_id: true,
  workspace_id: true,
  reviewer_note: true,
}).strict();
const publishedEdgeEvidenceLinkSchema = edgeEvidenceLinkSchema.omit({
  paper_id: true,
  workspace_id: true,
}).strict();
const publishedActivitySchema = activitySchema.omit({ paper_id: true, workspace_id: true }).strict();

export const publishedPaperSnapshotSchema = z.object({
  schema_version: z.literal(1),
  paper: publishedPaperSchema,
  source: publishedSourceSchema,
  sections: publishedSectionListSchema,
  compounds: z.array(publishedCompoundSchema),
  structures: z.array(publishedStructureSchema),
  structure_source_images: z.array(publishedStructureSourceImageSchema),
  lineages: z.array(publishedLineageSchema),
  lineage_members: z.array(publishedLineageMemberSchema),
  lineage_edges: z.array(publishedLineageEdgeSchema),
  evidence: z.array(publishedEvidenceSchema),
  edge_evidence_links: z.array(publishedEdgeEvidenceLinkSchema),
  activities: z.array(publishedActivitySchema),
}).strict();

export const publishedPaperListItemSchema = bibliographySchema.omit({ paper_id: true }).extend({
  paper_id: uuidSchema,
  version_number: z.number().int().positive(),
  content_hash: sha256Schema,
  published_at: timestampSchema,
}).strict();

export const publishedPaperListSchema = z.object({
  items: z.array(publishedPaperListItemSchema),
  total: z.number().int().nonnegative(),
}).strict().superRefine((value, context) => {
  if (value.items.length !== value.total) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Published Paper total is inconsistent" });
  }
});

export const publishedPaperDetailSchema = z.object({
  paper_id: uuidSchema,
  version_id: uuidSchema,
  version_number: z.number().int().positive(),
  content_hash: sha256Schema,
  published_at: timestampSchema,
  bibliography: bibliographySchema,
  snapshot: publishedPaperSnapshotSchema,
}).strict().superRefine((value, context) => {
  if (value.bibliography.paper_id !== value.paper_id
    || value.snapshot.paper.id !== value.paper_id) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Published Paper identity mismatch" });
  }
});

export const assignmentResponseSchema = z.object({
  review_task_id: uuidSchema,
  workspace_id: uuidSchema,
  paper_id: uuidSchema,
  assigned_reviewer_id: uuidSchema,
  task_status: reviewTaskStateSchema,
  task_version: z.number().int().positive(),
  workspace_state: workspaceStateSchema,
  workspace_version: z.number().int().positive(),
  sections: sectionListSchema,
}).strict().superRefine(addWorkflowPairIssue);

export const submissionMutationSchema = z.object({
  submission: paperSubmissionSchema,
  workspace_version: z.number().int().positive(),
}).strict().superRefine((value, context) => {
  if (value.workspace_version !== value.submission.workspace_version) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Submission response version mismatch" });
  }
});

export const adminDecisionSchema = z.object({
  id: uuidSchema,
  submission_id: uuidSchema,
  paper_id: uuidSchema,
  content_hash: sha256Schema,
  action: adminDecisionActionSchema,
  reason: z.string().min(1),
  decided_by_id: uuidSchema,
  idempotency_key: z.string().min(1),
  decided_at: timestampSchema,
}).strict();

export const publishedVersionSchema = z.object({
  id: uuidSchema,
  paper_id: uuidSchema,
  submission_id: uuidSchema,
  admin_decision_id: uuidSchema,
  version_number: z.number().int().positive(),
  snapshot: frozenPaperSnapshotSchema,
  content_hash: sha256Schema,
  decision_action: z.literal("approve"),
  published_by_id: uuidSchema,
  published_at: timestampSchema,
}).strict();

export const decisionMutationSchema = z.object({
  decision: adminDecisionSchema,
  published_version: publishedVersionSchema.nullable(),
}).strict().superRefine((value, context) => {
  if ((value.decision.action === "approve") !== (value.published_version !== null)) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Decision publication result is inconsistent" });
  }
  if (value.published_version && (
    value.published_version.admin_decision_id !== value.decision.id
      || value.published_version.submission_id !== value.decision.submission_id
      || value.published_version.paper_id !== value.decision.paper_id
      || value.published_version.content_hash !== value.decision.content_hash
  )) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Published Version identity mismatch" });
  }
});

export type PaperCatalogRow = z.infer<typeof paperCatalogRowSchema>;
export type PaperCatalogPage = z.infer<typeof paperCatalogPageSchema>;
export type ReviewTask = z.infer<typeof reviewTaskSchema>;
export type ReviewTaskList = z.infer<typeof reviewTaskListSchema>;
export type PaperWorkspace = z.infer<typeof paperWorkspaceSchema>;
export type ChangeEvent = z.infer<typeof changeEventSchema>;
export type PaperSubmission = z.infer<typeof paperSubmissionSchema>;
export type AdminSubmissionList = z.infer<typeof adminSubmissionListSchema>;
export type AdminSubmissionDetail = z.infer<typeof adminSubmissionDetailSchema>;
export type PublishedPaperList = z.infer<typeof publishedPaperListSchema>;
export type PublishedPaperDetail = z.infer<typeof publishedPaperDetailSchema>;
export type AssignmentResponse = z.infer<typeof assignmentResponseSchema>;
export type SubmissionMutation = z.infer<typeof submissionMutationSchema>;
export type DecisionMutation = z.infer<typeof decisionMutationSchema>;

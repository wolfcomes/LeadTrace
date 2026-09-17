export const publicationIds = {
  paper: "40000000-0000-4000-8000-000000000001",
  task: "40000000-0000-4000-8000-000000000002",
  workspace: "40000000-0000-4000-8000-000000000003",
  reviewer: "40000000-0000-4000-8000-000000000004",
  admin: "40000000-0000-4000-8000-000000000005",
  sourceAsset: "40000000-0000-4000-8000-000000000006",
  submission: "40000000-0000-4000-8000-000000000007",
  version: "40000000-0000-4000-8000-000000000008",
  decision: "40000000-0000-4000-8000-000000000009",
  compoundA: "40000000-0000-4000-8000-000000000011",
  compoundB: "40000000-0000-4000-8000-000000000012",
  structureA: "40000000-0000-4000-8000-000000000013",
  structureB: "40000000-0000-4000-8000-000000000014",
  depictionA: "40000000-0000-4000-8000-000000000015",
  sourceImage: "40000000-0000-4000-8000-000000000016",
  sourceCrop: "40000000-0000-4000-8000-000000000017",
  lineage: "40000000-0000-4000-8000-000000000018",
  memberA: "40000000-0000-4000-8000-000000000019",
  memberB: "40000000-0000-4000-8000-000000000020",
  edge: "40000000-0000-4000-8000-000000000021",
  evidence: "40000000-0000-4000-8000-000000000022",
  evidenceCrop: "40000000-0000-4000-8000-000000000023",
  evidenceLink: "40000000-0000-4000-8000-000000000024",
  activity: "40000000-0000-4000-8000-000000000025",
  aiRun: "40000000-0000-4000-8000-000000000026",
  aiEvent: "40000000-0000-4000-8000-000000000027",
  reviewerEvent: "40000000-0000-4000-8000-000000000028",
};

export const bibliography = {
  paper_id: publicationIds.paper,
  paper_key: "LT-JMC-2024-67-05-001",
  title: "Approved lead optimization study",
  journal: "Journal of Medicinal Chemistry",
  publication_year: 2024,
  volume: "67",
  issue: "5",
  doi: "10.1021/acs.jmedchem.4c00001",
};

const sectionKeys = [
  "bibliography",
  "compounds",
  "structures",
  "lineages",
  "edge_evidence",
  "activities",
] as const;

export const frozenSections = sectionKeys.map((section_key) => ({
  section_key,
  state: "completed" as const,
  note: null,
}));

export const frozenCompounds = [
  {
    id: publicationIds.compoundA,
    paper_id: publicationIds.paper,
    workspace_id: publicationIds.workspace,
    compound_label: "Lead 1",
    display_name: "Starting lead",
    description: "Initial root compound",
    sort_order: 0,
    created_by_kind: "ai" as const,
  },
  {
    id: publicationIds.compoundB,
    paper_id: publicationIds.paper,
    workspace_id: publicationIds.workspace,
    compound_label: "Compound 18",
    display_name: "Optimized compound",
    description: "Terminal product",
    sort_order: 1,
    created_by_kind: "reviewer" as const,
  },
];

export const frozenStructures = [
  {
    id: publicationIds.structureA,
    paper_id: publicationIds.paper,
    workspace_id: publicationIds.workspace,
    compound_id: publicationIds.compoundA,
    smiles: "CCO",
    canonical_smiles: "CCO",
    molfile: null,
    inchi: "InChI=1S/C2H6O",
    inchikey: "LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
    depiction_asset_id: publicationIds.depictionA,
    status: "reviewer_confirmed" as const,
    input_method: "ai_prefill" as const,
  },
  {
    id: publicationIds.structureB,
    paper_id: publicationIds.paper,
    workspace_id: publicationIds.workspace,
    compound_id: publicationIds.compoundB,
    smiles: "CCN",
    canonical_smiles: "CCN",
    molfile: null,
    inchi: "InChI=1S/C2H7N",
    inchikey: "QUSNBJAOOMFDIB-UHFFFAOYSA-N",
    depiction_asset_id: null,
    status: "reviewer_confirmed" as const,
    input_method: "manual_smiles" as const,
  },
];

export const frozenSourceImages = [{
  id: publicationIds.sourceImage,
  paper_id: publicationIds.paper,
  workspace_id: publicationIds.workspace,
  compound_id: publicationIds.compoundA,
  source_sha256: "a".repeat(64),
  page_number: 3,
  x0: "0.10",
  y0: "0.20",
  x1: "0.45",
  y1: "0.60",
  source_context: "Scheme 1",
  label: "Lead 1 source",
  reviewer_note: "Matches the PDF drawing",
  crop_status: "ready" as const,
  crop_asset_id: publicationIds.sourceCrop,
}];

export const frozenLineages = [{
  id: publicationIds.lineage,
  paper_id: publicationIds.paper,
  workspace_id: publicationIds.workspace,
  lineage_label: "Series A",
  description: "Lead 1 to Compound 18",
  sort_order: 0,
}];

export const frozenMembers = [
  {
    id: publicationIds.memberA,
    paper_id: publicationIds.paper,
    workspace_id: publicationIds.workspace,
    lineage_id: publicationIds.lineage,
    compound_id: publicationIds.compoundA,
    role: "root" as const,
    sort_order: 0,
  },
  {
    id: publicationIds.memberB,
    paper_id: publicationIds.paper,
    workspace_id: publicationIds.workspace,
    lineage_id: publicationIds.lineage,
    compound_id: publicationIds.compoundB,
    role: "terminal" as const,
    sort_order: 1,
  },
];

export const frozenEdges = [{
  id: publicationIds.edge,
  paper_id: publicationIds.paper,
  workspace_id: publicationIds.workspace,
  lineage_id: publicationIds.lineage,
  parent_compound_id: publicationIds.compoundA,
  child_compound_id: publicationIds.compoundB,
  relation_type: "lead_optimization",
  modification_summary: "Polar amine replacement",
  review_status: "reviewer_confirmed" as const,
  sort_order: 0,
}];

export const frozenEvidence = [{
  id: publicationIds.evidence,
  paper_id: publicationIds.paper,
  workspace_id: publicationIds.workspace,
  kind: "scheme" as const,
  source_sha256: "a".repeat(64),
  page_number: 4,
  x0: "0.15",
  y0: "0.25",
  x1: "0.75",
  y1: "0.85",
  quoted_text: "Lead 1 was optimized to compound 18.",
  caption: "Scheme 2",
  crop_asset_id: publicationIds.evidenceCrop,
  reviewer_note: "Direct transformation evidence",
}];

export const frozenEvidenceLinks = [{
  id: publicationIds.evidenceLink,
  paper_id: publicationIds.paper,
  workspace_id: publicationIds.workspace,
  edge_id: publicationIds.edge,
  evidence_id: publicationIds.evidence,
  role: "supports" as const,
}];

export const frozenActivities = [{
  id: publicationIds.activity,
  paper_id: publicationIds.paper,
  workspace_id: publicationIds.workspace,
  compound_id: publicationIds.compoundB,
  evidence_id: publicationIds.evidence,
  assay_name: "Cell potency",
  metric: "IC50",
  operator: "=" as const,
  value: "12.5",
  unit: "nM",
  context: "Human cells",
  sort_order: 0,
}];

export const frozenSnapshot = {
  schema_version: 1 as const,
  paper: {
    id: publicationIds.paper,
    paper_key: bibliography.paper_key,
    title: bibliography.title,
    journal: bibliography.journal,
    publication_year: bibliography.publication_year,
    volume: bibliography.volume,
    issue: bibliography.issue,
    doi: bibliography.doi,
    catalog_state: "verified" as const,
  },
  source: {
    asset_id: publicationIds.sourceAsset,
    source_root_key: "source_pdfs",
    source_key: "volume67 issue5/paper-01.pdf",
    sha256: "a".repeat(64),
    page_count: 12,
  },
  workspace_version: 9,
  sections: frozenSections,
  compounds: frozenCompounds,
  structures: frozenStructures,
  structure_source_images: frozenSourceImages,
  lineages: frozenLineages,
  lineage_members: frozenMembers,
  lineage_edges: frozenEdges,
  evidence: frozenEvidence,
  edge_evidence_links: frozenEvidenceLinks,
  activities: frozenActivities,
};

export const submission = {
  id: publicationIds.submission,
  paper_id: publicationIds.paper,
  workspace_id: publicationIds.workspace,
  review_task_id: publicationIds.task,
  submission_number: 2,
  idempotency_key: "submit-workspace-v9",
  snapshot: frozenSnapshot,
  content_hash: "b".repeat(64),
  workspace_version: 9,
  submitted_by_id: publicationIds.reviewer,
  reviewer_note: "All structures and transformations checked against the PDF.",
  submitted_at: "2026-09-17T02:00:00Z",
};

export const aiEvent = {
  id: publicationIds.aiEvent,
  paper_id: publicationIds.paper,
  workspace_id: publicationIds.workspace,
  entity_type: "structure",
  entity_id: publicationIds.structureA,
  action: "structure.create",
  before_value: null,
  after_value: { smiles: "CC" },
  actor_kind: "ai" as const,
  actor_id: null,
  ai_run_id: publicationIds.aiRun,
  occurred_at: "2026-09-17T00:30:00Z",
};

export const reviewerEvent = {
  id: publicationIds.reviewerEvent,
  paper_id: publicationIds.paper,
  workspace_id: publicationIds.workspace,
  entity_type: "structure",
  entity_id: publicationIds.structureA,
  action: "structure.update",
  before_value: { smiles: "CC" },
  after_value: { smiles: "CCO" },
  actor_kind: "reviewer" as const,
  actor_id: publicationIds.reviewer,
  ai_run_id: null,
  occurred_at: "2026-09-17T01:00:00Z",
};

export const adminSubmissionList = {
  items: [{
    submission_id: publicationIds.submission,
    paper_id: publicationIds.paper,
    workspace_id: publicationIds.workspace,
    submission_number: 2,
    content_hash: submission.content_hash,
    submitted_by_id: publicationIds.reviewer,
    submitted_at: submission.submitted_at,
    paper_key: bibliography.paper_key,
    title: bibliography.title,
  }],
  total: 1,
};

export const adminSubmissionDetail = {
  submission,
  bibliography,
  change_events: [aiEvent, reviewerEvent],
  reviewer_diff: [reviewerEvent],
};

export const publishedSnapshot = {
  schema_version: 1 as const,
  paper: {
    id: publicationIds.paper,
    paper_key: bibliography.paper_key,
    title: bibliography.title,
    journal: bibliography.journal,
    publication_year: bibliography.publication_year,
    volume: bibliography.volume,
    issue: bibliography.issue,
    doi: bibliography.doi,
  },
  source: { sha256: "a".repeat(64), page_count: 12 },
  sections: frozenSections.map(({ section_key, state }) => ({ section_key, state })),
  compounds: frozenCompounds.map(({ paper_id: _paper, workspace_id: _workspace, created_by_kind: _created, ...compound }) => compound),
  structures: frozenStructures.map(({ paper_id: _paper, workspace_id: _workspace, ...structure }) => structure),
  structure_source_images: frozenSourceImages.map(({ paper_id: _paper, workspace_id: _workspace, reviewer_note: _note, ...image }) => image),
  lineages: frozenLineages.map(({ paper_id: _paper, workspace_id: _workspace, ...lineage }) => lineage),
  lineage_members: frozenMembers.map(({ paper_id: _paper, workspace_id: _workspace, ...member }) => member),
  lineage_edges: frozenEdges.map(({ paper_id: _paper, workspace_id: _workspace, ...edge }) => edge),
  evidence: frozenEvidence.map(({ paper_id: _paper, workspace_id: _workspace, reviewer_note: _note, ...item }) => item),
  edge_evidence_links: frozenEvidenceLinks.map(({ paper_id: _paper, workspace_id: _workspace, ...link }) => link),
  activities: frozenActivities.map(({ paper_id: _paper, workspace_id: _workspace, ...activity }) => activity),
};

export const publishedList = {
  items: [{
    ...bibliography,
    version_number: 1,
    content_hash: submission.content_hash,
    published_at: "2026-09-17T03:00:00Z",
  }],
  total: 1,
};

export const publishedDetail = {
  paper_id: publicationIds.paper,
  version_id: publicationIds.version,
  version_number: 1,
  content_hash: submission.content_hash,
  published_at: "2026-09-17T03:00:00Z",
  bibliography,
  snapshot: publishedSnapshot,
};

export function decisionMutation(action: "approve" | "request_changes") {
  const decision = {
    id: publicationIds.decision,
    submission_id: publicationIds.submission,
    paper_id: publicationIds.paper,
    content_hash: submission.content_hash,
    action,
    reason: action === "approve" ? "Scientific record verified." : "Please clarify the terminal structure.",
    decided_by_id: publicationIds.admin,
    idempotency_key: `decision-${action}`,
    decided_at: "2026-09-17T03:00:00Z",
  };
  return {
    decision,
    published_version: action === "approve" ? {
      id: publicationIds.version,
      paper_id: publicationIds.paper,
      submission_id: publicationIds.submission,
      admin_decision_id: publicationIds.decision,
      version_number: 1,
      snapshot: frozenSnapshot,
      content_hash: submission.content_hash,
      decision_action: "approve" as const,
      published_by_id: publicationIds.admin,
      published_at: "2026-09-17T03:00:00Z",
    } : null,
  };
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "X-Request-ID": "task16-ui" },
  });
}

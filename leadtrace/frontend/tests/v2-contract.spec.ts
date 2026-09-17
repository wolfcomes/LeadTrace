import { afterEach, describe, expect, it, vi } from "vitest";

import {
  adminSubmissionDetailSchema,
  changeEventSchema,
  paperCatalogPageSchema,
  paperSubmissionSchema,
  paperWorkspaceSchema,
  publishedPaperDetailSchema,
  reviewTaskListSchema,
} from "../src/v2/types";
import { listPublishedPapers } from "../src/v2/api";


const ids = {
  paper: "10000000-0000-4000-8000-000000000001",
  source: "10000000-0000-4000-8000-000000000002",
  asset: "10000000-0000-4000-8000-000000000003",
  task: "10000000-0000-4000-8000-000000000004",
  workspace: "10000000-0000-4000-8000-000000000005",
  reviewer: "10000000-0000-4000-8000-000000000006",
  submission: "10000000-0000-4000-8000-000000000007",
  event: "10000000-0000-4000-8000-000000000008",
  version: "10000000-0000-4000-8000-000000000009",
};

const bibliography = {
  paper_id: ids.paper,
  paper_key: "LT-JMC-2024-67-05-001",
  title: "A lead-optimization study",
  journal: "Journal of Medicinal Chemistry",
  publication_year: 2024,
  volume: "67",
  issue: "5",
  doi: "10.1021/acs.jmedchem.4c00001",
};

const source = {
  asset_id: ids.asset,
  source_root_key: "source_pdfs",
  source_key: "volume67 issue5/paper-01.pdf",
};

const sectionKeys = [
  "bibliography",
  "compounds",
  "structures",
  "lineages",
  "edge_evidence",
  "activities",
] as const;

const sections = sectionKeys.map((section_key) => ({
  section_key,
  state: "pending" as const,
  note: null,
}));

const workspace = {
  id: ids.workspace,
  review_task_id: ids.task,
  assigned_reviewer_id: ids.reviewer,
  state: "editing" as const,
  version: 1,
  task_status: "assigned" as const,
  bibliography,
  source,
  sections,
};

const frozenSnapshot = {
  schema_version: 1 as const,
  paper: {
    id: ids.paper,
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
    ...source,
    sha256: "a".repeat(64),
    page_count: 12,
  },
  workspace_version: 1,
  sections,
  compounds: [],
  structures: [],
  structure_source_images: [],
  lineages: [],
  lineage_members: [],
  lineage_edges: [],
  evidence: [],
  edge_evidence_links: [],
  activities: [],
};

const submission = {
  id: ids.submission,
  paper_id: ids.paper,
  workspace_id: ids.workspace,
  review_task_id: ids.task,
  submission_number: 1,
  idempotency_key: "submit-1",
  snapshot: frozenSnapshot,
  content_hash: "b".repeat(64),
  workspace_version: 1,
  submitted_by_id: ids.reviewer,
  reviewer_note: "Ready for review",
  submitted_at: "2026-09-17T02:00:00Z",
};

const changeEvent = {
  id: ids.event,
  paper_id: ids.paper,
  workspace_id: ids.workspace,
  entity_type: "paper",
  entity_id: ids.paper,
  action: "bibliography.update",
  before_value: { title: "Before" },
  after_value: { title: bibliography.title },
  actor_kind: "reviewer" as const,
  actor_id: ids.reviewer,
  ai_run_id: null,
  occurred_at: "2026-09-17T01:00:00Z",
};

const publishedSnapshot = {
  schema_version: 1 as const,
  paper: {
    id: ids.paper,
    paper_key: bibliography.paper_key,
    title: bibliography.title,
    journal: bibliography.journal,
    publication_year: bibliography.publication_year,
    volume: bibliography.volume,
    issue: bibliography.issue,
    doi: bibliography.doi,
  },
  source: { sha256: "a".repeat(64), page_count: 12 },
  sections: sections.map(({ section_key, state }) => ({ section_key, state })),
  compounds: [],
  structures: [],
  structure_source_images: [],
  lineages: [],
  lineage_members: [],
  lineage_edges: [],
  evidence: [],
  edge_evidence_links: [],
  activities: [],
};


describe("paper-centric v2 response contracts", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("accepts catalog, task, workspace, event, submission, and published fixtures", () => {
    expect(paperCatalogPageSchema.parse({
      items: [{
        id: ids.paper,
        paper_key: bibliography.paper_key,
        title: bibliography.title,
        journal: bibliography.journal,
        publication_year: bibliography.publication_year,
        volume: bibliography.volume,
        issue: bibliography.issue,
        doi: bibliography.doi,
        catalog_state: "verified",
        source: {
          id: ids.source,
          ...source,
          sha256: "a".repeat(64),
          byte_size: 1024,
          page_count: 12,
          integrity_state: "verified",
        },
      }],
      total: 1,
      limit: 20,
      offset: 0,
    }).total).toBe(1);

    expect(reviewTaskListSchema.parse({
      items: [{
        review_task_id: ids.task,
        workspace_id: ids.workspace,
        paper_id: ids.paper,
        paper_key: bibliography.paper_key,
        title: bibliography.title,
        task_status: "assigned",
        task_version: 1,
        workspace_state: "editing",
        workspace_version: 1,
      }],
      total: 1,
    }).items).toHaveLength(1);
    expect(paperWorkspaceSchema.parse(workspace).sections).toHaveLength(6);
    expect(changeEventSchema.parse(changeEvent).action).toBe("bibliography.update");
    expect(paperSubmissionSchema.parse(submission).snapshot.paper.id).toBe(ids.paper);

    expect(adminSubmissionDetailSchema.parse({
      submission,
      bibliography,
      change_events: [changeEvent],
      reviewer_diff: [changeEvent],
    }).reviewer_diff).toHaveLength(1);

    expect(publishedPaperDetailSchema.parse({
      paper_id: ids.paper,
      version_id: ids.version,
      version_number: 1,
      content_hash: submission.content_hash,
      published_at: "2026-09-17T03:00:00Z",
      bibliography,
      snapshot: publishedSnapshot,
    }).snapshot.sections).toHaveLength(6);
  });

  it.each([
    "/srv/leadtrace/source.pdf",
    "C:\\leadtrace\\source.pdf",
    "../source.pdf",
    "volume67 issue5/../../source.pdf",
    "file:///srv/source.pdf",
  ])("rejects unsafe Source paths: %s", (sourceKey) => {
    expect(() => paperWorkspaceSchema.parse({
      ...workspace,
      source: { ...source, source_key: sourceKey },
    })).toThrow();
  });

  it("accepts a legal empty catalog page whose offset is beyond the current total", () => {
    expect(paperCatalogPageSchema.parse({
      items: [],
      total: 20,
      limit: 20,
      offset: 100,
    })).toEqual({
      items: [],
      total: 20,
      limit: 20,
      offset: 100,
    });
  });

  it("rejects duplicate or incomplete fixed sections and impossible workflow pairs", () => {
    expect(() => paperWorkspaceSchema.parse({
      ...workspace,
      sections: [...sections.slice(0, 5), sections[0]],
    })).toThrow();
    expect(() => paperWorkspaceSchema.parse({
      ...workspace,
      state: "submitted",
      task_status: "assigned",
    })).toThrow();
    expect(() => reviewTaskListSchema.parse({
      items: [{
        review_task_id: ids.task,
        workspace_id: ids.workspace,
        paper_id: ids.paper,
        paper_key: bibliography.paper_key,
        title: bibliography.title,
        task_status: "approved",
        task_version: 1,
        workspace_state: "editing",
        workspace_version: 1,
      }],
      total: 1,
    })).toThrow();
  });

  it("rejects frozen records whose Paper or Workspace identity crosses aggregates", () => {
    expect(() => paperSubmissionSchema.parse({
      ...submission,
      paper_id: "20000000-0000-4000-8000-000000000001",
    })).toThrow();
    expect(() => paperSubmissionSchema.parse({
      ...submission,
      snapshot: {
        ...frozenSnapshot,
        workspace_version: 2,
      },
    })).toThrow();
  });

  it("rejects leaked draft/internal fields from the formal Published projection", () => {
    expect(() => publishedPaperDetailSchema.parse({
      paper_id: ids.paper,
      version_id: ids.version,
      version_number: 1,
      content_hash: submission.content_hash,
      published_at: "2026-09-17T03:00:00Z",
      bibliography,
      snapshot: { ...publishedSnapshot, workspace_id: ids.workspace },
    })).toThrow();
    expect(() => publishedPaperDetailSchema.parse({
      paper_id: ids.paper,
      version_id: ids.version,
      version_number: 1,
      content_hash: submission.content_hash,
      published_at: "2026-09-17T03:00:00Z",
      bibliography,
      snapshot: {
        ...publishedSnapshot,
        source: { ...publishedSnapshot.source, asset_id: ids.asset },
      },
    })).toThrow();
  });

  it("accepts PostgreSQL Decimal values serialized in scientific notation", () => {
    expect(() => publishedPaperDetailSchema.parse({
      paper_id: ids.paper,
      version_id: ids.version,
      version_number: 1,
      content_hash: submission.content_hash,
      published_at: "2026-09-17T03:00:00Z",
      bibliography,
      snapshot: {
        ...publishedSnapshot,
        activities: [{
          id: "30000000-0000-4000-8000-000000000001",
          compound_id: "30000000-0000-4000-8000-000000000002",
          evidence_id: null,
          assay_name: "Cell viability",
          metric: "IC50",
          operator: "<",
          value: "1E-9",
          unit: "M",
          context: null,
          sort_order: 1,
        }],
      },
    })).not.toThrow();
  });

  it("uses the formal v2 endpoint and validates its response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      items: [{
        paper_id: ids.paper,
        paper_key: bibliography.paper_key,
        title: bibliography.title,
        journal: bibliography.journal,
        publication_year: bibliography.publication_year,
        volume: bibliography.volume,
        issue: bibliography.issue,
        doi: bibliography.doi,
        version_number: 1,
        content_hash: submission.content_hash,
        published_at: "2026-09-17T03:00:00Z",
      }],
      total: 1,
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await listPublishedPapers();

    expect(result.total).toBe(1);
    expect(fetchMock).toHaveBeenCalledWith("/api/v2/papers", expect.objectContaining({
      credentials: "same-origin",
    }));
  });
});

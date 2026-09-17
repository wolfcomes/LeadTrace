import { expect, test, type Page, type Route } from "@playwright/test";

import type {
  Activity,
  AdminSubmissionDetail,
  Compound,
  Evidence,
  EvidenceLink,
  Lineage,
  LineageEdge,
  LineageMember,
  PaperCatalogRow,
  PaperSubmission,
  PaperWorkspace,
  PublishedPaperDetail,
  Structure,
} from "../src/v2/types";
import { bibliography, publicationIds } from "../tests/paper-publication-v2-fixtures";


const sourceId = "40000000-0000-4000-8000-000000000010";
const sectionKeys = [
  "bibliography",
  "compounds",
  "structures",
  "lineages",
  "edge_evidence",
  "activities",
] as const;

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({
    status,
    contentType: "application/json",
    headers: { "X-Request-ID": "paper-centric-manual-e2e" },
    body: JSON.stringify(body),
  });
}

async function svg(route: Route): Promise<void> {
  await route.fulfill({
    status: 200,
    contentType: "image/svg+xml",
    body: "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'><path d='M1 5h8'/></svg>",
  });
}

async function login(page: Page, username: "admin" | "reviewer"): Promise<void> {
  await page.locator("#username").fill(username);
  await page.locator("#password").fill("test-password");
  await page.locator("button[type='submit']").click();
}

test("blank manual Paper flows from assignment through immutable publication", async ({ page }) => {
  let signedInAs: "admin" | "reviewer" | null = null;
  let assigned = false;
  let approved = false;
  let taskStatus: "assigned" | "submitted" | "approved" = "assigned";
  let workspaceState: "editing" | "submitted" | "approved" = "editing";
  let workspaceVersion = 1;
  let workspaceReadCount = 0;
  let submission: PaperSubmission | null = null;
  let decisionCount = 0;
  const forbiddenGenericAssetRequests: string[] = [];
  const sections: PaperWorkspace["sections"] = sectionKeys.map((section_key) => ({
    section_key,
    state: "pending",
    note: null,
  }));
  const compounds: Compound[] = [];
  const structures: Structure[] = [];
  const lineages: Lineage[] = [];
  const members: LineageMember[] = [];
  const edges: LineageEdge[] = [];
  const evidenceItems: Evidence[] = [];
  const evidenceLinks: EvidenceLink[] = [];
  const activities: Activity[] = [];

  const source = {
    asset_id: publicationIds.sourceAsset,
    source_root_key: "source_pdfs",
    source_key: "volume67 issue5/paper-01.pdf",
    sha256: "a".repeat(64),
    page_count: 12,
  };

  function workspace(): PaperWorkspace {
    return {
      id: publicationIds.workspace,
      review_task_id: publicationIds.task,
      assigned_reviewer_id: publicationIds.reviewer,
      state: workspaceState,
      version: workspaceVersion,
      task_status: taskStatus,
      bibliography,
      source,
      sections: sections.map((section) => ({ ...section })),
    };
  }

  function catalogPaper(): PaperCatalogRow {
    return {
      id: publicationIds.paper,
      paper_key: bibliography.paper_key,
      title: bibliography.title,
      journal: bibliography.journal,
      publication_year: bibliography.publication_year,
      volume: bibliography.volume,
      issue: bibliography.issue,
      doi: bibliography.doi,
      catalog_state: "verified",
      source: {
        id: sourceId,
        asset_id: source.asset_id,
        source_root_key: source.source_root_key,
        source_key: source.source_key,
        sha256: source.sha256,
        byte_size: 1024,
        page_count: source.page_count,
        integrity_state: "verified",
      },
      review: assigned ? {
        review_task_id: publicationIds.task,
        workspace_id: publicationIds.workspace,
        assigned_reviewer_id: publicationIds.reviewer,
        assignee_display_name: "试点 Reviewer",
        task_status: taskStatus,
        workspace_state: workspaceState,
        sections_resolved: sections.filter((section) => section.state !== "pending").length,
        sections_total: sections.length,
        submission_state: taskStatus === "assigned" ? "not_submitted" : taskStatus,
      } : null,
    };
  }

  function assertCsrf(route: Route, role: "admin" | "reviewer"): void {
    expect(route.request().headers()["x-csrf-token"]).toBe(`${role}-csrf`);
  }

  function advance(route: Route): Record<string, unknown> {
    assertCsrf(route, "reviewer");
    const body = route.request().postDataJSON() as Record<string, unknown>;
    expect(body.expected_workspace_version).toBe(workspaceVersion);
    workspaceVersion += 1;
    return body;
  }

  function frozenSnapshot(): PaperSubmission["snapshot"] {
    return {
      schema_version: 1,
      paper: {
        id: publicationIds.paper,
        paper_key: bibliography.paper_key,
        title: bibliography.title,
        journal: bibliography.journal,
        publication_year: bibliography.publication_year,
        volume: bibliography.volume,
        issue: bibliography.issue,
        doi: bibliography.doi,
        catalog_state: "verified",
      },
      source,
      workspace_version: workspaceVersion,
      sections: sections.map((section) => ({ ...section })),
      compounds: compounds.map((compound) => ({ ...compound })),
      structures: structures.map((structure) => ({ ...structure })),
      structure_source_images: [],
      lineages: lineages.map((lineage) => ({
        id: lineage.id,
        paper_id: lineage.paper_id,
        workspace_id: lineage.workspace_id,
        lineage_label: lineage.lineage_label,
        description: lineage.description,
        sort_order: lineage.sort_order,
      })),
      lineage_members: members.map((member) => ({ ...member })),
      lineage_edges: edges.map((edge) => ({ ...edge })),
      evidence: evidenceItems.map((item) => ({
        id: item.id,
        paper_id: item.paper_id,
        workspace_id: item.workspace_id,
        kind: item.kind,
        source_sha256: item.source_sha256,
        page_number: item.page_number,
        x0: item.bbox ? String(item.bbox.x0) : null,
        y0: item.bbox ? String(item.bbox.y0) : null,
        x1: item.bbox ? String(item.bbox.x1) : null,
        y1: item.bbox ? String(item.bbox.y1) : null,
        quoted_text: item.quoted_text,
        caption: item.caption,
        crop_asset_id: item.crop_asset_id,
        reviewer_note: item.reviewer_note,
      })),
      edge_evidence_links: evidenceLinks.map((link) => ({ ...link })),
      activities: activities.map((activity) => ({ ...activity })),
    };
  }

  function submissionDetail(): AdminSubmissionDetail {
    if (!submission) throw new Error("Submission has not been frozen");
    const reviewerEvent = {
      id: publicationIds.reviewerEvent,
      paper_id: publicationIds.paper,
      workspace_id: publicationIds.workspace,
      entity_type: "compound",
      entity_id: publicationIds.compoundA,
      action: "compound.create",
      before_value: null,
      after_value: { compound_label: "Lead 1" },
      actor_kind: "reviewer" as const,
      actor_id: publicationIds.reviewer,
      ai_run_id: null,
      occurred_at: "2026-09-17T01:00:00Z",
    };
    return {
      submission,
      bibliography,
      change_events: [reviewerEvent],
      reviewer_diff: [reviewerEvent],
    };
  }

  function publishedDetail(): PublishedPaperDetail {
    if (!submission || !approved) throw new Error("Paper has not been approved");
    const snapshot = submission.snapshot;
    return {
      paper_id: publicationIds.paper,
      version_id: publicationIds.version,
      version_number: 1,
      content_hash: submission.content_hash,
      published_at: "2026-09-17T03:00:00Z",
      bibliography,
      snapshot: {
        schema_version: 1,
        paper: {
          id: snapshot.paper.id,
          paper_key: snapshot.paper.paper_key,
          title: snapshot.paper.title,
          journal: snapshot.paper.journal,
          publication_year: snapshot.paper.publication_year,
          volume: snapshot.paper.volume,
          issue: snapshot.paper.issue,
          doi: snapshot.paper.doi,
        },
        source: { sha256: snapshot.source.sha256, page_count: snapshot.source.page_count },
        sections: snapshot.sections.map((section) => ({ section_key: section.section_key, state: section.state })),
        compounds: snapshot.compounds.map((compound) => ({
          id: compound.id,
          compound_label: compound.compound_label,
          display_name: compound.display_name,
          description: compound.description,
          sort_order: compound.sort_order,
        })),
        structures: snapshot.structures.map((structure) => ({
          id: structure.id,
          compound_id: structure.compound_id,
          smiles: structure.smiles,
          canonical_smiles: structure.canonical_smiles,
          molfile: structure.molfile,
          inchi: structure.inchi,
          inchikey: structure.inchikey,
          depiction_asset_id: structure.depiction_asset_id,
          status: structure.status,
          input_method: structure.input_method,
        })),
        structure_source_images: [],
        lineages: snapshot.lineages.map((lineage) => ({
          id: lineage.id,
          lineage_label: lineage.lineage_label,
          description: lineage.description,
          sort_order: lineage.sort_order,
        })),
        lineage_members: snapshot.lineage_members.map((member) => ({
          id: member.id,
          lineage_id: member.lineage_id,
          compound_id: member.compound_id,
          role: member.role,
          sort_order: member.sort_order,
        })),
        lineage_edges: snapshot.lineage_edges.map((edge) => ({
          id: edge.id,
          lineage_id: edge.lineage_id,
          parent_compound_id: edge.parent_compound_id,
          child_compound_id: edge.child_compound_id,
          relation_type: edge.relation_type,
          modification_summary: edge.modification_summary,
          review_status: edge.review_status,
          sort_order: edge.sort_order,
        })),
        evidence: snapshot.evidence.map((item) => ({
          id: item.id,
          kind: item.kind,
          source_sha256: item.source_sha256,
          page_number: item.page_number,
          x0: item.x0,
          y0: item.y0,
          x1: item.x1,
          y1: item.y1,
          quoted_text: item.quoted_text,
          caption: item.caption,
          crop_asset_id: item.crop_asset_id,
        })),
        edge_evidence_links: snapshot.edge_evidence_links.map((link) => ({
          id: link.id,
          edge_id: link.edge_id,
          evidence_id: link.evidence_id,
          role: link.role,
        })),
        activities: snapshot.activities.map((activity) => ({
          id: activity.id,
          compound_id: activity.compound_id,
          evidence_id: activity.evidence_id,
          assay_name: activity.assay_name,
          metric: activity.metric,
          operator: activity.operator,
          value: activity.value,
          unit: activity.unit,
          context: activity.context,
          sort_order: activity.sort_order,
        })),
      },
    };
  }

  await page.route(/\/api\/v[12]\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    if (path === "/api/v1/auth/session" && method === "GET") {
      if (!signedInAs) {
        await json(route, { code: "AUTHENTICATION_REQUIRED", message: "Sign in", details: {}, request_id: "manual-session" }, 401);
        return;
      }
      await json(route, {
        user: { username: signedInAs, display_name: signedInAs === "admin" ? "试点管理员" : "试点 Reviewer", role: signedInAs, must_change_password: false },
        csrf_token: `${signedInAs}-csrf`,
      });
      return;
    }
    if (path === "/api/v1/auth/login" && method === "POST") {
      const body = request.postDataJSON() as { username: "admin" | "reviewer" };
      signedInAs = body.username;
      await json(route, {
        user: { username: signedInAs, display_name: signedInAs === "admin" ? "试点管理员" : "试点 Reviewer", role: signedInAs, must_change_password: false },
        csrf_token: `${signedInAs}-csrf`,
      });
      return;
    }
    if (path === "/api/v1/auth/logout" && method === "POST") {
      if (signedInAs) assertCsrf(route, signedInAs);
      signedInAs = null;
      await route.fulfill({ status: 204 });
      return;
    }
    if (path === "/api/v1/users" && method === "GET") {
      await json(route, [
        { id: publicationIds.admin, username: "admin", display_name: "试点管理员", role: "admin", is_enabled: true, must_change_password: false },
        { id: publicationIds.reviewer, username: "reviewer", display_name: "试点 Reviewer", role: "reviewer", is_enabled: true, must_change_password: false },
      ]);
      return;
    }
    if (path === "/api/v2/admin/papers" && method === "GET") {
      await json(route, { items: [catalogPaper()], total: 1, limit: 20, offset: 0 });
      return;
    }
    if (path === `/api/v2/admin/papers/${publicationIds.paper}/assign` && method === "POST") {
      assertCsrf(route, "admin");
      expect(request.postDataJSON()).toEqual({ reviewer_id: publicationIds.reviewer });
      assigned = true;
      await json(route, {
        review_task_id: publicationIds.task,
        workspace_id: publicationIds.workspace,
        paper_id: publicationIds.paper,
        assigned_reviewer_id: publicationIds.reviewer,
        task_status: "assigned",
        task_version: 1,
        workspace_state: "editing",
        workspace_version: workspaceVersion,
        sections,
      }, 201);
      return;
    }
    if (path === "/api/v2/review/tasks" && method === "GET") {
      await json(route, {
        items: assigned ? [{
          review_task_id: publicationIds.task,
          workspace_id: publicationIds.workspace,
          paper_id: publicationIds.paper,
          paper_key: bibliography.paper_key,
          title: bibliography.title,
          task_status: taskStatus,
          task_version: taskStatus === "assigned" ? 1 : taskStatus === "submitted" ? 2 : 3,
          workspace_state: workspaceState,
          workspace_version: workspaceVersion,
        }] : [],
        total: assigned ? 1 : 0,
      });
      return;
    }
    if (path === `/api/v2/workspaces/${publicationIds.workspace}` && method === "GET") {
      workspaceReadCount += 1;
      await json(route, workspace());
      return;
    }
    const sectionMatch = path.match(new RegExp(`^/api/v2/workspaces/${publicationIds.workspace}/sections/([^/]+)$`));
    if (sectionMatch && method === "PUT") {
      const body = advance(route);
      const section = sections.find((item) => item.section_key === sectionMatch[1]);
      if (!section) throw new Error(`Unknown section ${sectionMatch[1]}`);
      section.state = body.state as PaperWorkspace["sections"][number]["state"];
      section.note = body.note as string | null;
      await json(route, workspace());
      return;
    }
    if (path === `/api/v2/workspaces/${publicationIds.workspace}/compounds`) {
      if (method === "GET") {
        await json(route, { workspace_id: publicationIds.workspace, workspace_version: workspaceVersion, items: compounds, total: compounds.length });
        return;
      }
      if (method === "POST") {
        const body = advance(route);
        const index = compounds.length;
        const compound: Compound = {
          id: index === 0 ? publicationIds.compoundA : publicationIds.compoundB,
          paper_id: publicationIds.paper,
          workspace_id: publicationIds.workspace,
          compound_label: String(body.compound_label),
          display_name: body.display_name as string | null,
          description: body.description as string | null,
          sort_order: index,
          created_by_kind: "reviewer",
        };
        compounds.push(compound);
        await json(route, { compound, workspace_version: workspaceVersion }, 201);
        return;
      }
    }
    const structureDepictionMatch = path.match(/^\/api\/v2\/compounds\/([^/]+)\/structure\/depiction$/);
    if (structureDepictionMatch && method === "GET") {
      await svg(route);
      return;
    }
    const sourceImagesMatch = path.match(/^\/api\/v2\/compounds\/([^/]+)\/source-images$/);
    if (sourceImagesMatch && method === "GET") {
      await json(route, { compound_id: sourceImagesMatch[1], workspace_version: workspaceVersion, items: [], total: 0 });
      return;
    }
    const structureMatch = path.match(/^\/api\/v2\/compounds\/([^/]+)\/structure$/);
    if (structureMatch) {
      const compoundId = structureMatch[1]!;
      if (method === "GET") {
        await json(route, { structure: structures.find((item) => item.compound_id === compoundId) ?? null, workspace_version: workspaceVersion });
        return;
      }
      if (method === "PUT") {
        const body = advance(route);
        const isReported = body.status !== "not_reported" && body.status !== "unresolved";
        const existing = structures.find((item) => item.compound_id === compoundId);
        const structure: Structure = {
          id: compoundId === publicationIds.compoundA ? publicationIds.structureA : publicationIds.structureB,
          paper_id: publicationIds.paper,
          workspace_id: publicationIds.workspace,
          compound_id: compoundId,
          smiles: isReported ? String(body.smiles) : null,
          canonical_smiles: isReported ? String(body.smiles) : null,
          molfile: body.molfile as string | null,
          inchi: isReported ? "InChI=1S/C2H6O" : null,
          inchikey: isReported ? "LFQSCWFLJHTTHZ-UHFFFAOYSA-N" : null,
          depiction_asset_id: isReported ? publicationIds.depictionA : null,
          status: body.status as Structure["status"],
          input_method: body.input_method as Structure["input_method"],
        };
        if (existing) structures.splice(structures.indexOf(existing), 1, structure);
        else structures.push(structure);
        await json(route, { structure, workspace_version: workspaceVersion });
        return;
      }
    }
    if (path === `/api/v2/workspaces/${publicationIds.workspace}/lineages`) {
      if (method === "GET") {
        await json(route, { workspace_id: publicationIds.workspace, workspace_version: workspaceVersion, items: lineages, total: lineages.length });
        return;
      }
      if (method === "POST") {
        const body = advance(route);
        const lineage: Lineage = {
          id: publicationIds.lineage,
          paper_id: publicationIds.paper,
          workspace_id: publicationIds.workspace,
          lineage_label: String(body.lineage_label),
          description: body.description as string | null,
          sort_order: 0,
          members: [],
          edges: [],
        };
        lineages.push(lineage);
        await json(route, { lineage, workspace_version: workspaceVersion }, 201);
        return;
      }
    }
    if (path === `/api/v2/lineages/${publicationIds.lineage}/members` && method === "POST") {
      const body = advance(route);
      const member: LineageMember = {
        id: members.length === 0 ? publicationIds.memberA : publicationIds.memberB,
        paper_id: publicationIds.paper,
        workspace_id: publicationIds.workspace,
        lineage_id: publicationIds.lineage,
        compound_id: String(body.compound_id),
        role: body.role as LineageMember["role"],
        sort_order: members.length,
      };
      members.push(member);
      lineages[0]?.members.push(member);
      await json(route, { member, workspace_version: workspaceVersion }, 201);
      return;
    }
    if (path === `/api/v2/lineages/${publicationIds.lineage}/edges` && method === "POST") {
      const body = advance(route);
      const edge: LineageEdge = {
        id: publicationIds.edge,
        paper_id: publicationIds.paper,
        workspace_id: publicationIds.workspace,
        lineage_id: publicationIds.lineage,
        parent_compound_id: String(body.parent_compound_id),
        child_compound_id: String(body.child_compound_id),
        relation_type: String(body.relation_type),
        modification_summary: body.modification_summary as string | null,
        review_status: body.review_status as LineageEdge["review_status"],
        sort_order: 0,
      };
      edges.push(edge);
      lineages[0]?.edges.push(edge);
      await json(route, { edge, workspace_version: workspaceVersion }, 201);
      return;
    }
    if (path === `/api/v2/workspaces/${publicationIds.workspace}/evidence`) {
      if (method === "GET") {
        await json(route, { workspace_id: publicationIds.workspace, workspace_version: workspaceVersion, items: evidenceItems, total: evidenceItems.length });
        return;
      }
      if (method === "POST") {
        const body = advance(route);
        const evidence: Evidence = {
          id: publicationIds.evidence,
          paper_id: publicationIds.paper,
          workspace_id: publicationIds.workspace,
          kind: body.kind as Evidence["kind"],
          source_sha256: String(body.source_sha256),
          page_number: Number(body.page_number),
          bbox: body.bbox as Evidence["bbox"],
          quoted_text: body.quoted_text as string | null,
          caption: body.caption as string | null,
          crop_asset_id: null,
          reviewer_note: body.reviewer_note as string | null,
        };
        evidenceItems.push(evidence);
        await json(route, { evidence, workspace_version: workspaceVersion }, 201);
        return;
      }
    }
    const evidenceLinksMatch = path.match(/^\/api\/v2\/lineage-edges\/([^/]+)\/evidence-links$/);
    if (evidenceLinksMatch) {
      const edgeId = evidenceLinksMatch[1]!;
      if (method === "GET") {
        const items = evidenceLinks.filter((link) => link.edge_id === edgeId);
        await json(route, { edge_id: edgeId, workspace_version: workspaceVersion, items, total: items.length });
        return;
      }
      if (method === "POST") {
        const body = advance(route);
        const link: EvidenceLink = {
          id: publicationIds.evidenceLink,
          paper_id: publicationIds.paper,
          workspace_id: publicationIds.workspace,
          edge_id: edgeId,
          evidence_id: String(body.evidence_id),
          role: body.role as EvidenceLink["role"],
        };
        evidenceLinks.push(link);
        await json(route, { link, workspace_version: workspaceVersion }, 201);
        return;
      }
    }
    const activitiesMatch = path.match(/^\/api\/v2\/compounds\/([^/]+)\/activities$/);
    if (activitiesMatch) {
      const compoundId = activitiesMatch[1]!;
      if (method === "GET") {
        const items = activities.filter((activity) => activity.compound_id === compoundId);
        await json(route, { compound_id: compoundId, workspace_version: workspaceVersion, items, total: items.length });
        return;
      }
      if (method === "POST") {
        const body = advance(route);
        const activity: Activity = {
          id: publicationIds.activity,
          paper_id: publicationIds.paper,
          workspace_id: publicationIds.workspace,
          compound_id: compoundId,
          evidence_id: body.evidence_id as string | null,
          assay_name: String(body.assay_name),
          metric: String(body.metric),
          operator: body.operator as Activity["operator"],
          value: String(body.value),
          unit: body.unit as string | null,
          context: body.context as string | null,
          sort_order: 0,
        };
        activities.push(activity);
        await json(route, { activity, workspace_version: workspaceVersion }, 201);
        return;
      }
    }
    if (path === `/api/v2/workspaces/${publicationIds.workspace}/submission-validation` && method === "GET") {
      const valid = sections.every((section) => section.state !== "pending")
        && compounds.length === 2
        && structures.length === 2
        && edges.length === 1
        && evidenceLinks.some((link) => link.edge_id === publicationIds.edge && link.role === "supports");
      await json(route, valid ? { valid: true, blockers: [] } : {
        valid: false,
        blockers: [{ code: "MANUAL_PATH_INCOMPLETE", message: "Complete the manual record", entity_type: "workspace", entity_id: null, section_key: null }],
      });
      return;
    }
    if (path === `/api/v2/workspaces/${publicationIds.workspace}/submit` && method === "POST") {
      const expectedVersion = workspaceVersion;
      const body = advance(route);
      const idempotencyKey = request.headers()["idempotency-key"];
      expect(idempotencyKey).toBe(`submit-${publicationIds.workspace}-v${expectedVersion}`);
      taskStatus = "submitted";
      workspaceState = "submitted";
      submission = {
        id: publicationIds.submission,
        paper_id: publicationIds.paper,
        workspace_id: publicationIds.workspace,
        review_task_id: publicationIds.task,
        submission_number: 1,
        idempotency_key: idempotencyKey!,
        snapshot: frozenSnapshot(),
        content_hash: "b".repeat(64),
        workspace_version: workspaceVersion,
        submitted_by_id: publicationIds.reviewer,
        reviewer_note: body.reviewer_note as string | null,
        submitted_at: "2026-09-17T02:00:00Z",
      };
      await json(route, { submission, workspace_version: workspaceVersion }, 201);
      return;
    }
    if (path === "/api/v2/admin/submissions" && method === "GET") {
      await json(route, submission ? {
        items: [{
          submission_id: submission.id,
          paper_id: submission.paper_id,
          workspace_id: submission.workspace_id,
          submission_number: submission.submission_number,
          content_hash: submission.content_hash,
          submitted_by_id: submission.submitted_by_id,
          submitted_at: submission.submitted_at,
          paper_key: bibliography.paper_key,
          title: bibliography.title,
        }],
        total: 1,
      } : { items: [], total: 0 });
      return;
    }
    if (path === `/api/v2/admin/submissions/${publicationIds.submission}` && method === "GET") {
      await json(route, submissionDetail());
      return;
    }
    if (path === `/api/v2/admin/submissions/${publicationIds.submission}/decisions` && method === "POST") {
      assertCsrf(route, "admin");
      if (!submission) throw new Error("Cannot approve without a Submission");
      decisionCount += 1;
      const body = request.postDataJSON() as { action: string; content_hash: string; reason: string };
      expect(body).toEqual({ action: "approve", content_hash: submission.content_hash, reason: "Source PDF and scientific lineage verified." });
      expect(request.headers()["idempotency-key"]).toBe(`approve-${submission.id}-${submission.content_hash}`);
      approved = true;
      taskStatus = "approved";
      workspaceState = "approved";
      const decision = {
        id: publicationIds.decision,
        submission_id: submission.id,
        paper_id: publicationIds.paper,
        content_hash: submission.content_hash,
        action: "approve" as const,
        reason: body.reason,
        decided_by_id: publicationIds.admin,
        idempotency_key: request.headers()["idempotency-key"]!,
        decided_at: "2026-09-17T03:00:00Z",
      };
      await json(route, {
        decision,
        published_version: {
          id: publicationIds.version,
          paper_id: publicationIds.paper,
          submission_id: submission.id,
          admin_decision_id: decision.id,
          version_number: 1,
          snapshot: submission.snapshot,
          content_hash: submission.content_hash,
          decision_action: "approve",
          published_by_id: publicationIds.admin,
          published_at: decision.decided_at,
        },
      }, 201);
      return;
    }
    if (path === "/api/v2/papers" && method === "GET") {
      await json(route, approved && submission ? {
        items: [{ ...bibliography, version_number: 1, content_hash: submission.content_hash, published_at: "2026-09-17T03:00:00Z" }],
        total: 1,
      } : { items: [], total: 0 });
      return;
    }
    if (path === `/api/v2/papers/${publicationIds.paper}` && method === "GET") {
      if (!approved) {
        await json(route, { code: "RESOURCE_NOT_FOUND", message: "Resource not found", details: {}, request_id: "manual-hidden" }, 404);
        return;
      }
      await json(route, publishedDetail());
      return;
    }
    if (path.startsWith(`/api/v2/papers/${publicationIds.paper}/assets/`) && method === "GET") {
      await svg(route);
      return;
    }
    if (path.startsWith("/api/v1/assets/") && method === "GET") {
      if (path === `/api/v1/assets/${publicationIds.depictionA}/content`) {
        await svg(route);
        return;
      }
      forbiddenGenericAssetRequests.push(path);
      await json(route, { code: "RESOURCE_NOT_FOUND", message: "Scoped asset hidden", details: {}, request_id: "manual-asset" }, 404);
      return;
    }

    throw new Error(`Unexpected ${method} request: ${path}`);
  });

  await page.goto("/admin/papers");
  await expect(page).toHaveURL(/\/login\?redirect=/);
  await login(page, "admin");
  await expect(page.getByRole("heading", { name: "文章目录" })).toBeVisible();
  await page.locator(`[data-paper-id='${publicationIds.paper}'] [data-assign]`).click();
  await expect(page.locator("[data-assignment-dialog]")).toBeVisible();
  await page.locator("[data-assignment-form] select").selectOption(publicationIds.reviewer);
  await page.getByRole("button", { name: "确认分配" }).click();
  await expect(page.locator(`[data-paper-id='${publicationIds.paper}']`)).toContainText("试点 Reviewer");

  await page.locator(".sign-out").click();
  await expect(page).toHaveURL(/\/login$/);
  await login(page, "reviewer");
  await page.getByRole("link", { name: "我的任务" }).click();
  await expect(page.getByRole("heading", { name: "我的任务" })).toBeVisible();
  await page.locator("[data-open-workspace]").click();
  await expect(page.locator("[data-paper-workspace]")).toContainText(bibliography.title);
  await expect(page.locator("[data-workspace-version]")).toContainText("v1");

  await page.getByRole("button", { name: "化合物与结构" }).click();
  await page.locator("[data-add-compound]").click();
  await page.getByLabel("Compound label").fill("Lead 1");
  await page.getByLabel("显示名称").fill("Starting lead");
  await page.getByRole("button", { name: "保存 Compound" }).click();
  await expect(page.locator(`[data-compound-id='${publicationIds.compoundA}']`)).toHaveClass(/selected/);
  await page.locator("[data-smiles-input]").fill("CCO");
  await page.locator("[data-save-structure]").click();
  await expect(page.locator("[data-confirm-structure]")).toBeEnabled();
  await page.locator("[data-confirm-structure]").click();
  await expect(page.locator("[data-structure-status]")).toContainText("Reviewer 已确认");

  await page.locator("[data-add-compound]").click();
  await page.getByLabel("Compound label").fill("Compound 18");
  await page.getByLabel("显示名称").fill("Optimized compound");
  await page.getByRole("button", { name: "保存 Compound" }).click();
  await expect(page.locator(`[data-compound-id='${publicationIds.compoundB}']`)).toHaveClass(/selected/);
  await page.locator("[data-mark-structure='not_reported']").click();
  await expect(page.locator("[data-structure-status]")).toContainText("文章未报告");

  await page.getByRole("button", { name: "Lineage", exact: true }).click();
  await page.locator("[data-add-lineage]").click();
  await page.locator("[data-lineage-label-input]").fill("Series A");
  await page.getByLabel("描述").fill("Lead 1 to Compound 18");
  await page.locator("[data-save-lineage]").click();
  await expect(page.locator(`[data-lineage-id='${publicationIds.lineage}']`)).toHaveClass(/selected/);
  const memberEditor = page.locator(".member-editor");
  await memberEditor.getByLabel("Compound").selectOption(publicationIds.compoundA);
  await memberEditor.getByLabel("角色").selectOption("root");
  await memberEditor.getByRole("button", { name: "添加 Member" }).click();
  await expect(page.locator("[data-member-role='root']")).toContainText("Lead 1");
  await memberEditor.getByLabel("Compound").selectOption(publicationIds.compoundB);
  await memberEditor.getByLabel("角色").selectOption("terminal");
  await memberEditor.getByRole("button", { name: "添加 Member" }).click();
  await expect(page.locator("[data-member-role='terminal']")).toContainText("Compound 18");
  const edgeEditor = page.locator(".edge-create-form");
  await edgeEditor.getByLabel("Parent").selectOption(publicationIds.compoundA);
  await edgeEditor.getByLabel("Child").selectOption(publicationIds.compoundB);
  await edgeEditor.getByLabel("修改摘要").fill("Polar amine replacement");
  await edgeEditor.getByLabel("审核状态").selectOption("reviewer_confirmed");
  await edgeEditor.getByRole("button", { name: "添加 Edge" }).click();
  await expect(page.locator(`[data-edge-id='${publicationIds.edge}']`)).toContainText("Lead 1 → Compound 18");

  await page.getByRole("button", { name: "证据与活性" }).click();
  await page.locator("[data-add-evidence]").click();
  await page.locator("[data-evidence-page]").fill("4");
  await page.locator("[data-evidence-quote]").fill("Lead 1 was optimized to compound 18.");
  await page.locator("[data-evidence-edge-choice]").check();
  await page.locator("[data-save-evidence]").click();
  await expect(page.locator("[data-edge-evidence-link]")).toContainText("supports");
  await page.locator("[data-add-activity]").click();
  const activityForm = page.locator(".activity-create-form");
  await activityForm.getByLabel("Compound").selectOption(publicationIds.compoundB);
  await activityForm.getByLabel("Assay").fill("Cell potency");
  await activityForm.getByLabel("Value").fill("12.5");
  await activityForm.getByLabel("Unit").fill("nM");
  await activityForm.getByRole("button", { name: "保存 Activity" }).click();
  await expect(page.locator("[data-activity-row]")).toContainText("12.5 nM");

  for (const sectionKey of sectionKeys) {
    const section = page.locator(`[data-section-key='${sectionKey}']`);
    await section.locator("[data-section-choice='completed']").click();
    await expect(section).toHaveAttribute("data-state", "completed");
  }
  await page.getByRole("button", { name: "检查与提交" }).click();
  await expect(page.locator("[data-valid='true']")).toContainText("提交检查已通过");
  await page.locator("[data-reviewer-note]").fill("Manual record checked against the Source PDF.");
  await page.locator("[data-reviewer-confirmation]").check();
  await page.locator("[data-submit-paper]").click();
  await expect(page.getByText("已提交给 Admin 审批", { exact: true })).toBeVisible();

  await page.locator(".sign-out").click();
  await login(page, "admin");
  await page.getByRole("link", { name: "提交审批" }).click();
  await expect(page.getByRole("heading", { name: "提交审批" })).toBeVisible();
  await expect(page.locator("[data-submission-row]")).toContainText(bibliography.title);
  await page.locator("[data-open-submission]").click();
  await expect(page.getByRole("heading", { name: "结构原图与 RDKit 对照" })).toBeVisible();
  await expect(page.locator("[data-submission-lineage]")).toContainText("Lead 1 → Compound 18");
  await expect(page.locator("[data-submission-lineage]")).toContainText("root");
  await expect(page.locator("[data-submission-lineage]")).toContainText("terminal");
  await expect(page.locator("[data-submission-evidence]")).toContainText("supports · Lead 1 → Compound 18");
  await expect(page.locator("[data-reviewer-diff]")).toContainText("Lead 1");
  await page.locator("[data-decision-reason]").fill("Source PDF and scientific lineage verified.");
  await page.locator("[data-approve-submission]").click();
  await expect(page.locator("[data-decision-success]")).toContainText("已批准并发布");
  expect(decisionCount).toBe(1);

  const workspaceReadsBeforeFormalPage = workspaceReadCount;
  await page.locator("[data-published-paper-link]").click();
  await expect(page.getByRole("heading", { name: bibliography.title })).toBeVisible();
  await expect(page.getByText("Lead 1 → Compound 18", { exact: true })).toBeVisible();
  await expect(page.getByText("supports · Lead 1 → Compound 18", { exact: true })).toBeVisible();
  await expect(page.getByText(/12\.5 nM/)).toBeVisible();
  await expect(page.locator("[data-published-depiction]")).toHaveAttribute(
    "src",
    `/api/v2/papers/${publicationIds.paper}/assets/${publicationIds.depictionA}`,
  );
  expect(workspaceReadCount).toBe(workspaceReadsBeforeFormalPage);
  expect(forbiddenGenericAssetRequests).toEqual([]);
});

import { expect, test, type Page, type Route } from "@playwright/test";


const ids = {
  paper: "81000000-0000-4000-8000-000000000001",
  task: "81000000-0000-4000-8000-000000000002",
  workspace: "81000000-0000-4000-8000-000000000003",
  reviewer: "81000000-0000-4000-8000-000000000004",
  source: "81000000-0000-4000-8000-000000000005",
  asset: "81000000-0000-4000-8000-000000000006",
  compound: "81000000-0000-4000-8000-000000000007",
  structure: "81000000-0000-4000-8000-000000000008",
  depiction: "81000000-0000-4000-8000-000000000009",
  run: "81000000-0000-4000-8000-000000000010",
};

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
    headers: { "X-Request-ID": "ai-prefill-e2e" },
    body: JSON.stringify(body),
  });
}

async function login(page: Page, username: "admin" | "reviewer"): Promise<void> {
  await page.locator("#username").fill(username);
  await page.locator("#password").fill("test-password");
  await page.locator("button[type='submit']").click();
}

test("AI prefill becomes ordinary Reviewer-owned records without overwrite", async ({ page }) => {
  let signedInAs: "admin" | "reviewer" | null = null;
  let workspaceVersion = 1;
  let aiState: "available" | "queued" | "running" | "succeeded" = "available";
  let aiStatusReads = 0;
  let aiPostCount = 0;
  let staleCatalogProjection = false;
  let structure = {
    id: ids.structure,
    paper_id: ids.paper,
    workspace_id: ids.workspace,
    compound_id: ids.compound,
    smiles: "CCO",
    molfile: null,
    canonical_smiles: "CCO",
    inchi: "InChI=1S/C2H6O",
    inchikey: "LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
    depiction_asset_id: ids.depiction,
    status: "draft",
    input_method: "ai_prefill",
  };

  const bibliography = {
    paper_id: ids.paper,
    paper_key: "LT-JMC-2024-67-05-017",
    title: "AI prefill lineage pilot",
    journal: "Journal of Medicinal Chemistry",
    publication_year: 2024,
    volume: "67",
    issue: "5",
    doi: "10.1021/acs.jmedchem.4c0017",
  };
  const source = {
    asset_id: ids.asset,
    source_root_key: "source_pdfs",
    source_key: "volume67 issue5/paper-17.pdf",
    sha256: "a".repeat(64),
    page_count: 12,
  };
  const compound = {
    id: ids.compound,
    paper_id: ids.paper,
    workspace_id: ids.workspace,
    compound_label: "7a",
    display_name: "Lead 7a",
    description: null,
    sort_order: 0,
    created_by_kind: "ai",
  };

  function workspace() {
    return {
      id: ids.workspace,
      review_task_id: ids.task,
      assigned_reviewer_id: ids.reviewer,
      state: "editing",
      version: workspaceVersion,
      task_status: "assigned",
      bibliography,
      source,
      sections: sectionKeys.map((section_key) => ({ section_key, state: "pending", note: null })),
    };
  }

  function run(status: "queued" | "running" | "succeeded") {
    return {
      id: ids.run,
      paper_id: ids.paper,
      workspace_id: ids.workspace,
      starting_workspace_version: 1,
      status,
      engine: "legacy_pipeline",
      engine_version: "pilot-v1",
      error_summary: null,
      queued_at: "2026-09-17T06:00:00Z",
      started_at: status === "queued" ? null : "2026-09-17T06:00:01Z",
      completed_at: status === "succeeded" ? "2026-09-17T06:00:02Z" : null,
    };
  }

  function aiProjection() {
    if (staleCatalogProjection) {
      return { run: null, can_start: true, blocked_reason: null };
    }
    if (aiState === "available") {
      return { run: null, can_start: true, blocked_reason: null };
    }
    return {
      run: run(aiState),
      can_start: false,
      blocked_reason: aiState === "succeeded"
        ? "Workspace has already been modified"
        : "AI prefill is already queued or running",
    };
  }

  function catalogPaper() {
    return {
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
        asset_id: ids.asset,
        source_root_key: source.source_root_key,
        source_key: source.source_key,
        sha256: source.sha256,
        byte_size: 123456,
        page_count: source.page_count,
        integrity_state: "verified",
      },
      review: {
        review_task_id: ids.task,
        workspace_id: ids.workspace,
        assigned_reviewer_id: ids.reviewer,
        assignee_display_name: "试点 Reviewer",
        task_status: "assigned",
        workspace_state: "editing",
        sections_resolved: 0,
        sections_total: 6,
        submission_state: "not_submitted",
      },
      ai_prefill: aiProjection(),
    };
  }

  await page.route(/\/api\/v[12]\//, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    if (path.endsWith('/review-progress')) return json(route, {}, 404);
    if (path.includes('/layouts/')) return json(route, {revision:0,mode:path.split('/').at(-1),positions:{},edge_controls:{}});

    if (path === "/api/v1/auth/session" && method === "GET") {
      if (!signedInAs) {
        await json(route, { code: "AUTHENTICATION_REQUIRED", message: "Sign in", details: {}, request_id: "ai-session" }, 401);
        return;
      }
      await json(route, {
        user: { username: signedInAs, display_name: signedInAs === "admin" ? "试点管理员" : "试点 Reviewer", role: signedInAs, must_change_password: false },
        csrf_token: `${signedInAs}-csrf`,
      });
      return;
    }
    if (path === "/api/v1/auth/login" && method === "POST") {
      signedInAs = (request.postDataJSON() as { username: "admin" | "reviewer" }).username;
      await json(route, {
        user: { username: signedInAs, display_name: signedInAs === "admin" ? "试点管理员" : "试点 Reviewer", role: signedInAs, must_change_password: false },
        csrf_token: `${signedInAs}-csrf`,
      });
      return;
    }
    if (path === "/api/v1/auth/logout" && method === "POST") {
      signedInAs = null;
      await route.fulfill({ status: 204 });
      return;
    }
    if (path === "/api/v2/papers" && method === "GET") {
      await json(route, { items: [], total: 0 });
      return;
    }
    if (path === `/api/v2/admin/papers/${ids.paper}` && method === "GET") {
      await json(route, catalogPaper());
      return;
    }
    if (path === `/api/v2/admin/papers/${ids.paper}/ai-prefill` && method === "POST") {
      aiPostCount += 1;
      expect(request.headers()["x-csrf-token"]).toBe("admin-csrf");
      if (workspaceVersion > 2) {
        await json(route, {
          code: "AI_PREFILL_UNAVAILABLE",
          message: "AI prefill requires a blank, untouched editing Workspace",
          details: {},
          request_id: "ai-race-conflict",
        }, 409);
        return;
      }
      aiState = "queued";
      await json(route, aiProjection(), 202);
      return;
    }
    if (path === `/api/v2/admin/papers/${ids.paper}/ai-prefill` && method === "GET") {
      aiStatusReads += 1;
      if (aiState === "queued") aiState = "running";
      else if (aiState === "running") {
        aiState = "succeeded";
        workspaceVersion = 2;
      }
      await json(route, aiProjection());
      return;
    }
    if (path === `/api/v2/workspaces/${ids.workspace}` && method === "GET") {
      await json(route, workspace());
      return;
    }
    if (path === `/api/v2/workspaces/${ids.workspace}/compounds` && method === "GET") {
      await json(route, { workspace_id: ids.workspace, workspace_version: workspaceVersion, items: [compound], total: 1 });
      return;
    }
    if (path === `/api/v2/workspaces/${ids.workspace}/evidence` && method === "GET") {
      await json(route, { workspace_id: ids.workspace, workspace_version: workspaceVersion, items: [], total: 0 });
      return;
    }
    if (path === `/api/v2/compounds/${ids.compound}/activities` && method === "GET") {
      await json(route, { compound_id: ids.compound, workspace_version: workspaceVersion, items: [], total: 0 });
      return;
    }
    if (path === `/api/v2/compounds/${ids.compound}/structure`) {
      if (method === "GET") {
        await json(route, { structure, workspace_version: workspaceVersion });
        return;
      }
      if (method === "PUT") {
        const body = request.postDataJSON() as Record<string, unknown>;
        expect(request.headers()["x-csrf-token"]).toBe("reviewer-csrf");
        expect(body.expected_workspace_version).toBe(2);
        workspaceVersion += 1;
        structure = {
          ...structure,
          smiles: String(body.smiles),
          canonical_smiles: String(body.smiles),
          input_method: String(body.input_method),
          status: String(body.status),
        };
        await json(route, { structure, workspace_version: workspaceVersion });
        return;
      }
    }
    if (path === `/api/v2/compounds/${ids.compound}/source-images` && method === "GET") {
      await json(route, { compound_id: ids.compound, workspace_version: workspaceVersion, items: [], total: 0 });
      return;
    }
    if (path === `/api/v2/compounds/${ids.compound}/structure/depiction` && method === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "image/svg+xml",
        body: "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'><path d='M1 5h8'/></svg>",
      });
      return;
    }
    if (path === `/api/v2/papers/${ids.paper}/assets/${ids.depiction}` && method === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "image/svg+xml",
        body: "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'><path d='M1 5h8'/></svg>",
      });
      return;
    }

    if (method === 'GET' && path.endsWith('/compound-highlights')) return json(route,{workspace_id:path.split('/').at(-2),workspace_version:workspaceVersion,items:[],total:0});
    throw new Error(`Unexpected ${method} request: ${path}`);
  });

  await page.goto(`/admin/papers/${ids.paper}`);
  await expect(page).toHaveURL(/\/login\?redirect=/);
  await login(page, "admin");
  await expect(page.locator("[data-ai-prefill-status]")).toContainText("可启动");
  await page.locator("[data-ai-prefill-start]").click();
  await expect(page.locator("[data-ai-prefill-status]")).toContainText("已排队");
  await expect(page.locator("[data-ai-prefill-status]")).toContainText("提取中", { timeout: 3_500 });
  await expect(page.locator("[data-ai-prefill-status]")).toContainText("预填完成", { timeout: 3_500 });
  expect(aiStatusReads).toBe(2);
  expect(aiPostCount).toBe(1);

  await page.locator(".sign-out").click();
  await login(page, "reviewer");
  await page.goto(`/review/papers/${ids.paper}?workspace=${ids.workspace}&tab=compounds`);
  await expect(page.locator("[data-workspace-version]")).toContainText("v2");
  await expect(page.locator("[data-structure-input-method]")).toContainText("AI 预填");
  await expect(page.locator("[data-smiles-input]")).toHaveValue("CCO");
  await page.locator("[data-smiles-input]").fill("CCN");
  await page.locator("[data-save-structure]").click();
  await expect(page.locator("[data-workspace-version]")).toContainText("v3");
  await expect(page.locator("[data-smiles-input]")).toHaveValue("CCN");
  expect(structure.id).toBe(ids.structure);

  staleCatalogProjection = true;
  await page.locator(".sign-out").click();
  await login(page, "admin");
  await page.goto(`/admin/papers/${ids.paper}`);
  await expect(page.locator("[data-ai-prefill-start]")).toBeEnabled();
  await page.locator("[data-ai-prefill-start]").click();
  await expect(page.locator("[data-ai-prefill-error]")).toContainText("ai-race-conflict");
  await page.waitForTimeout(250);

  expect(aiPostCount).toBe(2);
  expect(structure.id).toBe(ids.structure);
  expect(structure.smiles).toBe("CCN");
  await expect(page.locator("body")).not.toContainText("/data/home/");
  await expect(page.locator("body")).not.toContainText("storage_key");
});

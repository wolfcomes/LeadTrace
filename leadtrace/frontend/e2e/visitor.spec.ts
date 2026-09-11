import { expect, test } from "@playwright/test";


const release = {
  id: "10000000-0000-4000-8000-000000000001",
  key: "baseline-2026-09-11",
  title: "LeadTrace verified baseline",
  published_at: "2026-09-11T01:00:00+00:00",
};
const paperId = "20000000-0000-4000-8000-000000000001";

test("Visitor browses only the current release with shareable filters", async ({ page }) => {
  await page.route("**/api/v1/auth/session", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        user: { username: "visitor.one", display_name: "访客一", role: "visitor", must_change_password: false },
        csrf_token: "visitor-csrf",
      }),
    });
  });
  await page.route("**/api/v1/papers?**", async (route) => {
    const requestUrl = new URL(route.request().url());
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        request_id: "visitor-e2e-list",
        release,
        pagination: { page: Number(requestUrl.searchParams.get("page") ?? 1), page_size: 20, total_items: 25, total_pages: 2 },
        filters: {
          search: requestUrl.searchParams.get("search"),
          target: requestUrl.searchParams.get("target"),
          has_lineage: requestUrl.searchParams.get("has_lineage"),
          review_status: requestUrl.searchParams.get("review_status"),
          doi: null,
          relation_status: null,
          structure_state: null,
          sort: "manifest",
        },
        items: [{
          id: paperId,
          revision_id: "20000000-0000-4000-8000-000000000002",
          paper_key: "paper-24",
          doi: "10.1000/paper-24",
          title: "Published optimization study 24",
          year: "2026",
          target: "Kinase A",
          review_status: "unreviewed",
        }],
      }),
    });
  });
  await page.route(`**/api/v1/papers/${paperId}`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        request_id: "visitor-e2e-detail",
        release,
        paper: {
          id: paperId,
          revision_id: "20000000-0000-4000-8000-000000000002",
          paper_key: "paper-24",
          doi: "10.1000/paper-24",
          title: "Published optimization study 24",
          year: "2026",
          target: "Kinase A",
          review_status: "unreviewed",
        },
        compounds: [
          { id: "30000000-0000-4000-8000-000000000001", revision_id: "31000000-0000-4000-8000-000000000001", local_identity: "CMP-PARENT", label: "26a′" },
          { id: "30000000-0000-4000-8000-000000000002", revision_id: "31000000-0000-4000-8000-000000000002", local_identity: "CMP-DERIVED", label: "26b" },
          { id: "30000000-0000-4000-8000-000000000003", revision_id: "31000000-0000-4000-8000-000000000003", local_identity: "CMP-UNRESOLVED", label: "27" },
        ],
        lineages: [{ id: "40000000-0000-4000-8000-000000000001", revision_id: "41000000-0000-4000-8000-000000000001", lineage_key: "LINEAGE-1" }],
        lineage_edges: [
          { id: "50000000-0000-4000-8000-000000000001", revision_id: "51000000-0000-4000-8000-000000000001", lineage_id: "40000000-0000-4000-8000-000000000001", parent_compound_id: "30000000-0000-4000-8000-000000000001", derived_compound_id: "30000000-0000-4000-8000-000000000002", relation_type: "direct_optimization", relation_status: "text_explicit", pair_ready: true },
          { id: "50000000-0000-4000-8000-000000000002", revision_id: "51000000-0000-4000-8000-000000000002", lineage_id: "40000000-0000-4000-8000-000000000001", parent_compound_id: null, derived_compound_id: "30000000-0000-4000-8000-000000000003", relation_type: null, relation_status: "unresolved", pair_ready: false },
        ],
        structures: [
          { id: "60000000-0000-4000-8000-000000000000", revision_id: "61000000-0000-4000-8000-000000000000", compound_id: "30000000-0000-4000-8000-000000000001", state: "structure_confirmed", canonical_smiles: "CCO" },
          { id: "60000000-0000-4000-8000-000000000001", revision_id: "61000000-0000-4000-8000-000000000001", compound_id: "30000000-0000-4000-8000-000000000002", state: "structure_confirmed", canonical_smiles: "CCN" },
        ],
        evidence: [{ id: "70000000-0000-4000-8000-000000000001", revision_id: "71000000-0000-4000-8000-000000000001", state: "confirmed", text: "Potency improved." }],
        activities: [{ id: "80000000-0000-4000-8000-000000000001", revision_id: "81000000-0000-4000-8000-000000000001", compound_id: "30000000-0000-4000-8000-000000000002", state: "confirmed", metric: "IC50", value: "12", unit: "nM", qualifier: "=" }],
        quality_summary: {
          relations: { resolved: 1, total: 2 },
          structures: { confirmed: 1, total: 1 },
          pair_ready: { eligible: 1, total: 2 },
          human_review: { reviewed: 0, total: 11 },
        },
      }),
    });
  });
  await page.route("**/api/v1/papers/*/source-pdf", async (route) => {
    await route.fulfill({
      status: 403,
      contentType: "application/json",
      body: JSON.stringify({ code: "PERMISSION_DENIED", message: "Permission denied", details: {}, request_id: "visitor-pdf-denied" }),
    });
  });

  await page.goto("/papers?search=kinase&target=Kinase%20A&has_lineage=true&page=2");
  await expect(page.getByLabel("搜索文献")).toHaveValue("kinase");
  await expect(page.getByLabel("研究靶点")).toHaveValue("Kinase A");
  await expect(page.getByRole("navigation", { name: "文献分页" }).getByText("第 2 / 2 页")).toBeVisible();
  expect(await page.evaluate(() => [...document.fonts].some(
    (font) => font.family === "Noto Sans SC Variable" && font.status === "loaded",
  ))).toBe(true);

  await page.getByLabel("搜索文献").fill("protease");
  await page.getByRole("button", { name: "应用筛选" }).click();
  await expect(page).toHaveURL(/search=protease/);
  await expect(page).toHaveURL(/target=Kinase(?:%20|\+)A/);
  await expect(page).toHaveURL(/has_lineage=true/);
  await expect(page).toHaveURL(/page=1/);
  await page.screenshot({ path: "test-results/visitor-library.png", fullPage: true });

  await page.getByRole("link", { name: "Published optimization study 24", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Published optimization study 24" })).toBeVisible();
  await expect(page.getByText("LINEAGE-1")).toBeVisible();
  await expect(page.locator("[data-edge-status='unresolved']")).toContainText("关系待解析");
  await expect(page.getByText("CCN", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("已核查证据")).toBeVisible();
  await expect(page.getByText("Potency improved.")).toBeVisible();
  await expect(page.getByRole("link", { name: /原始 PDF/ })).toHaveCount(0);
  await page.screenshot({ path: "test-results/visitor-detail.png", fullPage: true });

  const fullPdfStatus = await page.evaluate(async (id) => {
    const response = await fetch(`/api/v1/papers/${id}/source-pdf`);
    return response.status;
  }, paperId);
  expect(fullPdfStatus).toBe(403);
});

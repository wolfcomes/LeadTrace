import { createHash } from "node:crypto";
import { lstatSync, readFileSync, writeFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

// Real backend/database only: this suite deliberately contains no route mocks.
test("Preview login, pinned PDF, structure, evidence and reviewer edit", async ({ page }, testInfo) => {
  const credentialsPath = process.env.PREVIEW_LIVE_CREDENTIALS_FILE!;
  const info = lstatSync(credentialsPath);
  if (!info.isFile() || info.isSymbolicLink() || (info.mode & 0o777) !== 0o600 || info.uid !== process.getuid?.()) {
    throw new Error("Preview credentials must be an owned mode-0600 regular file");
  }
  const credentials = JSON.parse(readFileSync(credentialsPath, "utf8"));
  const account = credentials.accounts.find((item: { username: string }) => item.username === "preview-reviewer");
  if (!account) throw new Error("Preview Reviewer account is missing");

  await page.goto("/login");
  await expect(page.locator("[data-preview-environment]")).toContainText("预览环境");
  const environment = await page.request.get("/api/preview/environment");
  expect(environment.ok()).toBe(true);
  const identity = await environment.json();
  expect(identity.environment).toBe("preview");
  expect(identity.frontend_available).toBe(true);
  await page.locator("#username").fill(account.username);
  await page.locator("#password").fill(account.password);
  await page.locator("button[type='submit']").click();
  await expect(page).not.toHaveURL(/\/login/);
  await page.goto("/review/tasks");
  await expect(page.locator("[data-review-task]").first()).toBeVisible();
  const taskResponse = await page.request.get("/api/v2/review/tasks");
  expect(taskResponse.ok()).toBe(true);
  const tasks = (await taskResponse.json()).items;
  const requestedPaper = process.env.PREVIEW_LIVE_PAPER_KEY;
  const task = requestedPaper ? tasks.find((item: { paper_key: string }) => item.paper_key === requestedPaper) : tasks[0];
  if (!task) throw new Error("No assigned Preview paper matches the requested paper key");
  const workspaceResponse = await page.request.get(`/api/v2/workspaces/${task.workspace_id}`);
  expect(workspaceResponse.ok()).toBe(true);
  const workspace = await workspaceResponse.json();
  const pdf = await page.request.get(`/api/v2/papers/${task.paper_id}/source-pdf`);
  expect(pdf.ok()).toBe(true);
  expect(pdf.headers()["content-type"]).toContain("application/pdf");
  const pdfBytes = await pdf.body();
  expect(pdfBytes.subarray(0, 5).toString()).toBe("%PDF-");
  expect(createHash("sha256").update(pdfBytes).digest("hex")).toBe(workspace.source.sha256);

  await page.goto(`/review/papers/${task.paper_id}?workspace=${task.workspace_id}&tab=compounds`);
  await expect(page.locator("[data-compound-row]").first()).toBeVisible();
  const depiction = page.locator('[data-structure-comparison] img[alt$="的 RDKit 图"]').first();
  await expect(depiction).toBeVisible();
  await expect.poll(() => depiction.evaluate((element) => (element as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  await page.locator("[data-capture-source-image]").click();
  const canvas = page.locator("[data-pdf-canvas]").first();
  await expect(canvas).toBeVisible();
  await expect(page.locator(".pdf-page-shell.is-rendered").first()).toBeVisible();
  await expect.poll(() => canvas.evaluate((element) => (element as HTMLCanvasElement).width)).toBeGreaterThan(300);
  const banner = await page.locator("[data-preview-environment]").boundingBox();
  const topbar = await page.locator("[data-app-topbar]").boundingBox();
  expect(topbar!.y).toBeGreaterThanOrEqual(banner!.y + banner!.height);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath("structures-and-source-pdf.png"), fullPage: true });
  await page.getByRole("button", { name: "Lineage", exact: true }).click();
  const graph = page.locator("[data-lineage-graph]").first();
  await expect(graph).toBeVisible();
  await expect.poll(async () => Number(await graph.getAttribute("data-edge-count"))).toBeGreaterThan(0);
  await expect(graph.locator("canvas").first()).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath("lineage.png"), fullPage: true });
  await expect(page.locator('[data-lineage-group="sar"]')).toBeVisible();
  await expect(page.locator('[data-lineage-group="synthesis"]')).toBeVisible();
  await page.locator('[data-lineage-group="synthesis"]').click();
  const synthesisCard = page.locator('[data-lineage-card]').first();
  await expect(synthesisCard).toBeVisible();
  await synthesisCard.locator("button").first().click();
  await expect(page.locator('[data-lineage-graph][data-display-mode="points"]')).toBeVisible();
  await expect(page.locator('[data-open-edge]').first()).toBeVisible();
  await page.locator('[data-open-edge]').first().click();
  await expect(page.locator("[data-edge-detail]")).toBeVisible();
  await expect(page.locator("[data-edge-endpoint]").first()).toBeVisible();
  await expect(page.locator("[data-edge-evidence-link], .evidence-empty").first()).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath("edge-detail.png"), fullPage: true });

  if (process.env.PREVIEW_LIVE_EDIT === "1") {
    // The note is deliberately a visible review record retained for child
    // Candidate export; scientific labels/SMILES remain unchanged.
    await page.getByRole("button", { name: "化合物与结构", exact: true }).click();
    await page.locator("[data-edit-compound]").first().click();
    const description = page.locator("[data-edit-compound-description]");
    const note = "[Preview automated browser check] 自动化检查已打开 PDF、结构与 Evidence；科学结论仍待人工确认。";
    const original = await description.inputValue();
    await description.fill(original.includes(note) ? original : `${original}${original ? "\n" : ""}${note}`);
    const saved = page.waitForResponse((response) => response.url().includes("/api/v2/compounds/") && response.request().method() === "PATCH");
    await page.locator("[data-save-compound]").click();
    expect((await saved).ok()).toBe(true);
    await page.reload();
    await page.locator("[data-edit-compound]").first().click();
    expect(await page.locator("[data-edit-compound-description]").inputValue()).toContain(note);
  }
  await page.getByRole("button", { name: "化合物与结构", exact: true }).click();
  const compoundsResponse = await page.request.get(`/api/v2/workspaces/${task.workspace_id}/compounds`);
  expect(compoundsResponse.ok()).toBe(true);
  const compounds = (await compoundsResponse.json()).items as Array<{ id: string }>;
  let activityCompoundId: string | undefined;
  for (const compound of compounds) {
    const activitiesResponse = await page.request.get(`/api/v2/compounds/${compound.id}/activities`);
    expect(activitiesResponse.ok()).toBe(true);
    if (((await activitiesResponse.json()).items as unknown[]).length > 0) {
      activityCompoundId = compound.id;
      break;
    }
  }
  expect(activityCompoundId).toBeTruthy();
  await page.locator(`[data-compound-id="${activityCompoundId}"] > button`).first().click();
  await expect(page.locator("[data-activity-count]")).toBeVisible();
  await expect(page.locator("[data-activity-row]").first()).toBeVisible();
  await expect(page.locator('[data-structure-comparison] img[alt$="的 RDKit 图"]').first()).toBeVisible();
  const finalWorkspaceResponse = await page.request.get(`/api/v2/workspaces/${task.workspace_id}`);
  expect(finalWorkspaceResponse.ok()).toBe(true);
  const finalWorkspace = await finalWorkspaceResponse.json();
  const checks = JSON.stringify({
    instance_id: identity.instance_id, paper_key: task.paper_key, workspace_id: task.workspace_id,
    workspace_version: finalWorkspace.version,
    source_sha256: workspace.source.sha256, reviewer_edit: process.env.PREVIEW_LIVE_EDIT === "1",
  }, null, 2);
  writeFileSync(testInfo.outputPath("preview-checks.json"), checks);
  await testInfo.attach("preview-checks", { body: checks, contentType: "application/json" });
});

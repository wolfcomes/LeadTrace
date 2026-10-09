import { expect, test } from "@playwright/test";
const id = (n: number) =>
  `92000000-0000-4000-8000-${String(n).padStart(12, "0")}`;

test("admin selects independent models, views errors, and confirms an archive on synthetic data", async ({
  page,
}) => {
  const paper = id(1),
    workspace = id(2);
  let management = {
    paper_id: paper,
    paper_key: "SYNTHETIC-018",
    workspace_id: workspace,
    workspace_version: 3,
    task_version: 2,
    assignment_state: "assigned",
    assigned_reviewer_id: id(4),
    counts: { compounds: 68, edges: 54, activities: 90 },
    archives: [],
    archive_root: "/test/article-archives",
  };
  const preset = {
    id: "deepseek",
    label: "DeepSeek",
    adapter: "dsh",
    model: "deepseek-flash",
    efforts: ["high", "max"],
    default_effort: "max",
    available: true,
    unavailable_reason: null,
  };
  const job = {
    id: id(7),
    paper_id: paper,
    paper_key: "SYNTHETIC-018",
    paper_title: "Synthetic task center example",
    workspace_id: workspace,
    workspace_version: 2,
    action: "review",
    preset_id: "deepseek",
    model: "deepseek-flash",
    reasoning_effort: "max",
    state: "partial",
    delivery_state: "not_applicable",
    stage: "validating",
    error_code: "INCOMPLETE_COVERAGE",
    error_message: "Three structures remain unchecked.",
    created_at: "2026-10-08T00:00:00Z",
    started_at: "2026-10-08T00:01:00Z",
    finished_at: "2026-10-08T00:30:00Z",
    heartbeat_at: "2026-10-08T00:30:00Z",
    timeout_seconds: 3600,
    attempt: 1,
    parent_job_id: null,
    result_summary: {
      missing_review_targets: 3,
      findings: [
        {
          domain: "compound",
          ref: "23",
          verdict: "incorrect",
          reason: "Ring system requires confirmation",
        },
      ],
      report_available: true,
    },
    can_cancel: false,
    can_retry: true,
  };
  let started: Record<string, unknown> | undefined;
  let archived: Record<string, unknown> | undefined;
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith("/api/")) return route.continue();
    const reply = (body: unknown, status = 200) =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    if (path === "/api/preview/environment") return reply({}, 404);
    if (path.endsWith("/auth/session"))
      return reply({
        user: {
          username: "admin",
          display_name: "Admin",
          role: "admin",
          must_change_password: false,
        },
        csrf_token: "synthetic",
      });
    if (path === `/api/v2/admin/papers/${paper}`)
      return reply({
        id: paper,
        paper_key: "SYNTHETIC-018",
        title: "Synthetic task center example",
        journal: "Example journal",
        publication_year: 2026,
        volume: "1",
        issue: "1",
        doi: null,
        catalog_state: "verified",
        source: {
          id: id(5),
          asset_id: id(6),
          source_root_key: "source_pdfs",
          source_key: "synthetic.pdf",
          sha256: "a".repeat(64),
          byte_size: 5000,
          page_count: 1,
          integrity_state: "verified",
        },
        review: {
          review_task_id: id(3),
          workspace_id: management.workspace_id,
          assigned_reviewer_id: management.assigned_reviewer_id,
          assignee_display_name: management.assigned_reviewer_id
            ? "Reviewer"
            : null,
          task_status: management.assignment_state,
          workspace_state: "editing",
          sections_resolved: 0,
          sections_total: 6,
          submission_state: "not_submitted",
        },
        ai_prefill: {
          run: null,
          can_start: false,
          blocked_reason: "Workspace already modified",
        },
      });
    if (path.endsWith("/management")) return reply(management);
    if (path === "/api/v2/admin/ai-tasks")
      return reply({
        items: [job],
        total: 1,
        settings: { max_concurrent: 4 },
        worker: { online: true, last_seen_at: "2026-10-08T00:31:00Z" },
        presets: [
          preset,
          {
            ...preset,
            id: "codex",
            label: "Codex/OpenAI",
            adapter: "codex",
            model: "gpt-test",
            efforts: ["low", "high"],
            default_effort: "high",
          },
        ],
      });
    if (path.endsWith("/report"))
      return reply({
        job_id: job.id,
        reviewed_workspace_version: 2,
        coverage: {
          expected: 68,
          reviewed: 65,
          missing: [{ domain: "compound", ref: "26" }],
        },
        findings: [
          {
            domain: "compound",
            ref: "23",
            verdict: "incorrect",
            reason: "Ring system requires confirmation",
            checked_fields: ["smiles"],
          },
        ],
      });
    if (
      path === `/api/v2/admin/papers/${paper}/ai-tasks` &&
      route.request().method() === "POST"
    ) {
      started = route.request().postDataJSON();
      return reply({
        ...job,
        id: id(8),
        state: "queued",
        workspace_version: 3,
        model: "gpt-test",
        reasoning_effort: "high",
      });
    }
    if (path.endsWith("/archive-reset")) {
      archived = route.request().postDataJSON();
      management = {
        ...management,
        workspace_id: id(9),
        workspace_version: 1,
        task_version: 1,
        assignment_state: "unassigned",
        assigned_reviewer_id: null as never,
        counts: { compounds: 0, edges: 0, activities: 0 },
      };
      return reply(management);
    }
    return reply({ code: "NOT_FOUND", request_id: "synthetic" }, 404);
  });
  await page.goto(`/admin/papers/${paper}`);
  const consolePanel = page.locator("[data-ai-task-console]");
  await expect(consolePanel).toContainText("全站并发上限：4");
  await expect(page.locator("[data-start-prefill]")).toBeDisabled();
  await page.locator("[data-review-model]").selectOption("codex");
  await expect(page.locator("[data-review-effort]")).toHaveValue("high");
  await expect(page.locator("[data-producer-effort]")).toHaveValue("max");
  await page.locator("[data-start-review]").click();
  await expect.poll(() => started?.action).toBe("review");
  expect(started).toMatchObject({
    preset_id: "codex",
    reasoning_effort: "high",
    expected_workspace_version: 3,
    expected_workspace_id: workspace,
    expected_task_version: 2,
  });
  await page.locator("[data-view-report]").click();
  await expect(consolePanel).toContainText("65 / 68");
  await page.locator("[data-language-switch]").selectOption("en");
  await expect(consolePanel).toContainText("Independent review");
  await expect(consolePanel).toContainText(
    "Three structures remain unchecked.",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  await page.locator("[data-open-reset]").click();
  await expect(page.getByRole("dialog")).toContainText(
    "/test/article-archives",
  );
  await expect(page.locator("[data-confirm-reset]")).toBeDisabled();
  await page.locator("[data-reset-paper-key]").fill("SYNTHETIC-018");
  await page.locator("[data-confirm-reset]").click();
  await expect.poll(() => archived?.confirm_paper_key).toBe("SYNTHETIC-018");
  expect(archived).toMatchObject({
    expected_workspace_id: workspace,
    expected_workspace_version: 3,
    expected_task_version: 2,
  });
  await expect(page.locator("[data-start-prefill]")).toBeEnabled();
});

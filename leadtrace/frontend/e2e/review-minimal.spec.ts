import { expect, test, type BrowserContext, type Page, type Route } from "@playwright/test";


const paperId = "20000000-0000-4000-8000-000000000001";
const reviewerAId = "30000000-0000-4000-8000-000000000001";
const releaseId = "40000000-0000-4000-8000-000000000001";
const taskId = "50000000-0000-4000-8000-000000000001";
const changesetId = "60000000-0000-4000-8000-000000000001";
const itemId = "70000000-0000-4000-8000-000000000001";
const evidenceItemId = "70000000-0000-4000-8000-000000000002";
const baseRevisionId = "80000000-0000-4000-8000-000000000001";
const proposedRevisionId = "80000000-0000-4000-8000-000000000002";

const release = {
  id: releaseId,
  key: "baseline-2026-09-12",
  title: "LeadTrace verified baseline",
  published_at: "2026-09-12T00:00:00Z",
  verification_status: "unverified",
};

const draft = {
  id: changesetId,
  review_task_id: taskId,
  paper_id: paperId,
  owner_id: reviewerAId,
  base_release_id: releaseId,
  title: "Reviewer A metadata verification",
  reason: "Compare Paper metadata and evidence against the source",
  workflow_state: "draft",
  version: 3,
  validation_results: {},
  submitted_snapshot: null,
  submitted_content_hash: null,
  submitted_at: null,
  created_at: "2026-09-12T01:00:00Z",
  updated_at: "2026-09-12T01:30:00Z",
};

const paperItem = {
  id: itemId,
  changeset_id: changesetId,
  paper_id: paperId,
  object_id: paperId,
  object_kind: "paper",
  base_revision_id: baseRevisionId,
  proposed_revision_id: proposedRevisionId,
  proposed_snapshot: {
    normalized_values: {
      title_guess: "Published optimization study 24",
      year: "2026",
      target: "Kinase A",
      review_status: "unreviewed",
    },
  },
  content_hash: "a".repeat(64),
  sequence: 1,
  changeset_version: 3,
  created_at: "2026-09-12T01:10:00Z",
};

const evidenceItem = {
  ...paperItem,
  id: evidenceItemId,
  object_id: "71000000-0000-4000-8000-000000000001",
  object_kind: "evidence",
  base_revision_id: "81000000-0000-4000-8000-000000000001",
  proposed_revision_id: "81000000-0000-4000-8000-000000000002",
  proposed_snapshot: {
    normalized_values: {
      evidence_text: "Published evidence excerpt",
      source_locator: "page 4",
    },
  },
  content_hash: "b".repeat(64),
  sequence: 2,
};

const diff = [{
  object_id: paperId,
  object_kind: "paper",
  base_revision_id: baseRevisionId,
  proposed_revision_id: proposedRevisionId,
  change_type: "update",
  changes: [{
    path: "/normalized_values/review_status",
    category: "state",
    before_present: true,
    after_present: true,
    before: "unreviewed",
    after: "reviewed",
  }],
}];

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({
    status,
    contentType: "application/json",
    headers: { "X-Request-ID": "review-minimal-e2e" },
    body: JSON.stringify(body),
  });
}

async function mockSession(
  context: BrowserContext,
  username: string,
  displayName: string,
  role: "visitor" | "reviewer",
): Promise<void> {
  await context.route("**/api/v1/auth/session", async (route) => {
    await json(route, {
      user: { username, display_name: displayName, role, must_change_password: false },
      csrf_token: `${username}-csrf`,
    });
  });
}

async function mockPublishedPaper(page: Page): Promise<void> {
  await page.route(`**/api/v1/papers/${paperId}`, async (route) => {
    await json(route, {
      request_id: "visitor-published-paper",
      release,
      paper: {
        id: paperId,
        revision_id: baseRevisionId,
        paper_key: "paper-24",
        doi: "10.1000/paper-24",
        title: "Published optimization study 24",
        year: "2026",
        target: "Kinase A",
        review_status: "unreviewed",
      },
      compounds: [],
      lineages: [],
      lineage_edges: [],
      structures: [],
      evidence: [{
        id: evidenceItem.object_id,
        revision_id: evidenceItem.base_revision_id,
        state: "confirmed",
        text: "Published evidence excerpt",
      }],
      activities: [],
      quality_summary: {
        relations: { resolved: 0, total: 0 },
        structures: { confirmed: 0, total: 0 },
        pair_ready: { eligible: 0, total: 0 },
        human_review: { reviewed: 0, total: 2 },
      },
    });
  });
}

test("isolates Reviewer drafts, exposes conflicts, and keeps publication approval-gated", async ({ browser }) => {
  const reviewerAContext = await browser.newContext();
  const reviewerBContext = await browser.newContext();
  const visitorContext = await browser.newContext();

  try {
    await mockSession(reviewerAContext, "reviewer.a", "核查员 A", "reviewer");
    await mockSession(reviewerBContext, "reviewer.b", "核查员 B", "reviewer");
    await mockSession(visitorContext, "visitor.one", "访客一", "visitor");

    const reviewerAPage = await reviewerAContext.newPage();
    const reviewerBPage = await reviewerBContext.newPage();
    const visitorPage = await visitorContext.newPage();
    let conflictReturned = false;

    await reviewerAPage.route(`**/api/v1/review/changesets/${changesetId}`, async (route) => {
      await json(route, draft);
    });
    await reviewerAPage.route(`**/api/v1/review/changesets/${changesetId}/items`, async (route) => {
      await json(route, [paperItem, evidenceItem]);
    });
    await reviewerAPage.route(`**/api/v1/review/changesets/${changesetId}/diff`, async (route) => {
      await json(route, diff);
    });
    await reviewerAPage.route(`**/api/v1/review/changesets/${changesetId}/items/${itemId}`, async (route) => {
      conflictReturned = true;
      await json(route, {
        code: "REVISION_CONFLICT",
        message: "Changeset version conflict",
        details: { expected_version: 3, current_version: 4 },
        request_id: "reviewer-a-stale-save",
      }, 409);
    });
    await reviewerAPage.route(`**/api/v1/review/changesets/${changesetId}/submit`, async (route) => {
      await json(route, {
        ...draft,
        workflow_state: "submitted",
        version: 4,
        submitted_snapshot: { item_ids: [itemId, evidenceItemId] },
        submitted_content_hash: "c".repeat(64),
        submitted_at: "2026-09-12T02:00:00Z",
      });
    });

    await reviewerBPage.route("**/api/v1/review/tasks", async (route) => json(route, []));
    await reviewerBPage.route("**/api/v1/review/changesets", async (route) => json(route, []));
    await reviewerBPage.route(`**/api/v1/review/changesets/${changesetId}`, async (route) => {
      await json(route, {
        code: "RESOURCE_NOT_FOUND",
        message: "Resource not found",
        details: {},
        request_id: "reviewer-b-draft-denied",
      }, 404);
    });
    await mockPublishedPaper(visitorPage);

    await reviewerBPage.goto("/review/changesets");
    await expect(reviewerBPage.getByRole("heading", { name: "暂无修改集" })).toBeVisible();
    await expect(reviewerBPage.getByText(draft.title)).toHaveCount(0);
    await reviewerBPage.goto(`/review/changesets/${changesetId}`);
    await expect(reviewerBPage.getByRole("heading", { name: "未找到修改集" })).toBeVisible();

    await reviewerAPage.goto(`/review/changesets/${changesetId}`);
    const paperTitleField = reviewerAPage.locator("#paper-title-field");
    await expect(paperTitleField).toHaveValue("Published optimization study 24");
    await paperTitleField.fill("Reviewer A local correction");
    const conflictDialog = reviewerAPage.getByRole("dialog", { name: "草稿已被其他会话更新" });
    await expect(conflictDialog).toBeVisible();
    await expect(conflictDialog).toContainText("本地基于版本3");
    await expect(conflictDialog).toContainText("服务端当前版本4");
    expect(conflictReturned).toBe(true);
    await conflictDialog.getByRole("button", { name: "使用服务端版本" }).click();
    await expect(conflictDialog).toBeHidden();
    await reviewerAPage.evaluate(() => window.scrollTo(0, 0));
    await reviewerAPage.screenshot({ path: "test-results/reviewer-editor.png", fullPage: true });

    await visitorPage.goto(`/papers/${paperId}`);
    await expect(visitorPage.getByRole("heading", { name: "Published optimization study 24" })).toBeVisible();
    await expect(visitorPage.getByText("Reviewer A local correction")).toHaveCount(0);
    const publishedTitle = await visitorPage.evaluate(async (id) => {
      const response = await fetch(`/api/v1/papers/${id}`);
      const payload = await response.json() as { paper: { title: string } };
      return payload.paper.title;
    }, paperId);
    expect(publishedTitle).toBe("Published optimization study 24");

    await reviewerAPage.getByRole("button", { name: "提交与审批" }).click();
    await reviewerAPage.getByRole("button", { name: "提交管理员审批" }).click();
    await expect(reviewerAPage.getByText("已提交，等待管理员审批")).toBeVisible();
    const submittedState = reviewerAPage.locator(".state-label[data-state='submitted']");
    await expect(submittedState).toHaveText("待管理员审批");
    expect(await submittedState.evaluate((element) => getComputedStyle(element).fontFamily)).toContain(
      "Noto Sans SC Variable",
    );
    await reviewerAPage.evaluate(() => window.scrollTo(0, 0));
    await reviewerAPage.screenshot({ path: "test-results/reviewer-submitted.png", fullPage: true });
  } finally {
    await reviewerAContext.close();
    await reviewerBContext.close();
    await visitorContext.close();
  }
});

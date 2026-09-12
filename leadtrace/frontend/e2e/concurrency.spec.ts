import { expect, test, type BrowserContext, type Route } from "@playwright/test";


const changesetId = "60000000-0000-4000-8000-000000000001";
const reviewerId = "30000000-0000-4000-8000-000000000001";
const taskId = "50000000-0000-4000-8000-000000000001";
const paperId = "20000000-0000-4000-8000-000000000001";
const releaseId = "40000000-0000-4000-8000-000000000001";

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({
    status,
    contentType: "application/json",
    headers: { "X-Request-ID": "concurrency-e2e" },
    body: JSON.stringify(body),
  });
}

async function mockReviewer(context: BrowserContext, username: string): Promise<void> {
  await context.route("**/api/v1/auth/session", async (route) => json(route, {
    user: {
      username,
      display_name: username,
      role: "reviewer",
      must_change_password: false,
    },
    csrf_token: `${username}-csrf`,
  }));
}

test("two editors preserve both drafts when the second save is stale", async ({ browser }) => {
  let serverTitle = "Shared review";
  let serverVersion = 1;
  const changeset = () => ({
    id: changesetId,
    review_task_id: taskId,
    paper_id: paperId,
    owner_id: reviewerId,
    base_release_id: releaseId,
    title: serverTitle,
    reason: "Review shared metadata",
    workflow_state: "draft",
    version: serverVersion,
    validation_results: {},
    submitted_snapshot: null,
    submitted_content_hash: null,
    submitted_at: null,
    created_at: "2026-09-12T01:00:00Z",
    updated_at: "2026-09-12T01:00:00Z",
  });
  const firstContext = await browser.newContext();
  const secondContext = await browser.newContext();
  try {
    await mockReviewer(firstContext, "reviewer.concurrent.a");
    await mockReviewer(secondContext, "reviewer.concurrent.b");
    const installChangesetRoutes = async (context: BrowserContext): Promise<void> => {
      await context.route(`**/api/v1/review/changesets/${changesetId}`, async (route) => {
        if (route.request().method() === "PATCH") {
          const payload = route.request().postDataJSON() as {
            expected_version: number;
            title: string;
          };
          if (payload.expected_version !== serverVersion) {
            await json(route, {
              code: "REVISION_CONFLICT",
              message: "Changeset version conflict",
              details: {
                expected_version: payload.expected_version,
                current_version: serverVersion,
              },
              request_id: "concurrency-stale-save",
            }, 409);
            return;
          }
          serverTitle = payload.title;
          serverVersion += 1;
        }
        await json(route, changeset());
      });
      await context.route(`**/api/v1/review/changesets/${changesetId}/items`, async (route) => json(route, []));
      await context.route(`**/api/v1/review/changesets/${changesetId}/diff`, async (route) => json(route, []));
    };
    await installChangesetRoutes(firstContext);
    await installChangesetRoutes(secondContext);
    const first = await firstContext.newPage();
    const second = await secondContext.newPage();

    await Promise.all([
      first.goto(`/review/changesets/${changesetId}`),
      second.goto(`/review/changesets/${changesetId}`),
    ]);
    const firstTitle = first.getByLabel("修改集标题");
    const secondTitle = second.getByLabel("修改集标题");
    await expect(firstTitle).toHaveValue("Shared review");
    await expect(secondTitle).toHaveValue("Shared review");

    await firstTitle.fill("Reviewer A correction");
    await expect(first.locator("[data-save-state='saved']")).toBeVisible();
    expect(serverTitle).toBe("Reviewer A correction");
    expect(serverVersion).toBe(2);

    await secondTitle.fill("Reviewer B independent correction");
    const conflict = second.getByRole("dialog", { name: "草稿已被其他会话更新" });
    await expect(conflict).toBeVisible();
    await expect(conflict).toContainText("本地基于版本1");
    await expect(conflict).toContainText("服务端当前版本2");
    await expect(secondTitle).toHaveValue("Reviewer B independent correction");
    expect(serverTitle).toBe("Reviewer A correction");
  } finally {
    await firstContext.close();
    await secondContext.close();
  }
});

import { expect, test, type Locator } from "@playwright/test";

import { expectNoHorizontalPageOverflow } from "./support/layout";


function contrastRatio(foreground: string, background: string): number {
  const luminance = (value: string): number => {
    const channels = value.match(/[\d.]+/g)?.slice(0, 3).map(Number) ?? [];
    if (channels.length !== 3) throw new Error(`Unsupported color: ${value}`);
    const [red, green, blue] = channels.map((channel) => {
      const normalized = channel / 255;
      return normalized <= 0.04045
        ? normalized / 12.92
        : ((normalized + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
  };
  const light = Math.max(luminance(foreground), luminance(background));
  const dark = Math.min(luminance(foreground), luminance(background));
  return (light + 0.05) / (dark + 0.05);
}


async function mockAnonymousSession(page: import("@playwright/test").Page): Promise<void> {
  await page.route("**/api/v1/auth/session", async (route) => {
    await route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({
        code: "AUTHENTICATION_REQUIRED",
        message: "Authentication required",
        details: {},
        request_id: "accessibility-session",
      }),
    });
  });
}

async function expectVisibleFocus(locator: Locator): Promise<void> {
  await locator.focus();
  const indicator = await locator.evaluate((element) => {
    const style = getComputedStyle(element);
    return { outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth };
  });
  expect(indicator.outlineStyle).not.toBe("none");
  expect(indicator.outlineWidth).not.toBe("0px");
}

test("login is keyboard operable, labelled, zoom-safe, and exposes errors", async ({ page }) => {
  await mockAnonymousSession(page);
  await page.route("**/api/v1/auth/login", async (route) => {
    await route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({
        code: "AUTHENTICATION_REQUIRED",
        message: "Authentication required",
        details: {},
        request_id: "accessibility-login",
      }),
    });
  });
  await page.goto("/login");

  const username = page.getByLabel("用户名");
  const password = page.getByLabel("密码");
  const submit = page.getByRole("button", { name: "登录" });
  await expect(username).toBeFocused();
  await expect(username).toHaveAttribute("autocomplete", "username");
  await expect(password).toHaveAttribute("autocomplete", "current-password");

  await page.keyboard.press("Tab");
  await expect(password).toBeFocused();
  const focusIndicator = await password.evaluate((element) => {
    const style = getComputedStyle(element);
    return `${style.outlineStyle}|${style.boxShadow}|${style.borderColor}`;
  });
  expect(focusIndicator).not.toBe("none|none|rgb(197, 208, 201)");

  await password.fill("space remains inside input");
  await page.keyboard.press("Space");
  await expect(page).toHaveURL(/\/login$/);
  await expect(password).toHaveValue("space remains inside input ");
  await username.fill("unknown.user");
  await expectVisibleFocus(submit);
  await submit.click();
  const alert = page.getByRole("alert");
  await expect(alert).toBeVisible();
  await expect(alert).not.toBeEmpty();
  await expect(alert.locator("[aria-hidden='true']")).toHaveCount(1);
  await expect(alert).toHaveAttribute("id", "login-error");
  await expect(username).toHaveAttribute("aria-describedby", "login-error");
  await expect(password).toHaveAttribute("aria-describedby", "login-error");

  const buttonColors = await submit.evaluate((element) => {
    const style = getComputedStyle(element);
    return { foreground: style.color, background: style.backgroundColor };
  });
  expect(contrastRatio(buttonColors.foreground, buttonColors.background)).toBeGreaterThanOrEqual(4.5);

  // A 1280px desktop viewport at 200% browser zoom has a 640px CSS viewport.
  await page.setViewportSize({ width: 640, height: 720 });
  const overflows = await page.evaluate(() => (
    document.documentElement.scrollWidth > document.documentElement.clientWidth + 1
  ));
  expect(overflows).toBe(false);
});


test("application shell provides landmarks, skip navigation, and visible focus", async ({ page }) => {
  await page.route("**/api/v1/auth/session", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        user: {
          username: "visitor.accessibility",
          display_name: "可访问性访客",
          role: "visitor",
          must_change_password: false,
        },
        csrf_token: "accessibility-csrf",
      }),
    });
  });
  await page.route("**/api/v1/published/overview", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        request_id: "accessibility-overview",
        release: {
          id: "10000000-0000-4000-8000-000000000001",
          key: "r1",
          title: '<img src=x onerror="window.__leadtraceXss=1">',
          published_at: "2026-09-12T00:00:00Z",
          verification_status: "unverified",
        },
        metrics: Object.fromEntries(
          ["corpus", "lineage", "relation", "structure", "pair", "human_review"].map(
            (key) => [key, { numerator: 1, denominator: 1, unit: key }],
          ),
        ),
      }),
    });
  });
  await page.goto("/overview");

  await expect(page.getByRole("navigation", { name: "主导航" })).toBeVisible();
  await expect(page.getByRole("main")).toHaveAttribute("id", "main-content");
  await page.keyboard.press("Tab");
  const skipLink = page.getByRole("link", { name: "跳到主要内容" });
  await expect(skipLink).toBeFocused();
  await expect(skipLink).toBeVisible();
  await skipLink.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();
  await expect(page.getByText('<img src=x onerror="window.__leadtraceXss=1">')).toBeVisible();
  expect(await page.evaluate(() => (window as typeof window & { __leadtraceXss?: number }).__leadtraceXss)).toBeUndefined();

  await expect(page.getByRole("heading", { name: "发布数据概览", level: 1 })).toBeVisible();
  await expectVisibleFocus(page.getByRole("link", { name: "文献库" }));
  await page.emulateMedia({ reducedMotion: "reduce" });
  const reducedMotion = await page.getByRole("link", { name: "文献库" }).evaluate((element) => {
    const style = getComputedStyle(element);
    return { transitionDuration: style.transitionDuration, animationDuration: style.animationDuration };
  });
  expect(parseFloat(reducedMotion.transitionDuration)).toBeLessThanOrEqual(0.01);
  expect(parseFloat(reducedMotion.animationDuration)).toBeLessThanOrEqual(0.01);

  await expectNoHorizontalPageOverflow(page);
});


test("review status uses readable text in addition to color", async ({ page }) => {
  await page.route("**/api/v1/auth/session", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        user: {
          username: "reviewer.accessibility",
          display_name: "可访问性核查员",
          role: "reviewer",
          must_change_password: false,
        },
        csrf_token: "accessibility-csrf",
      }),
    });
  });
  await page.route("**/api/v1/review/tasks", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([{
        id: "20000000-0000-4000-8000-000000000001",
        paper_id: "20000000-0000-4000-8000-000000000002",
        assigned_reviewer_id: "20000000-0000-4000-8000-000000000003",
        created_by_id: "20000000-0000-4000-8000-000000000004",
        status: "changes_requested",
        priority: 70,
        version: 2,
        created_at: "2026-09-12T00:00:00Z",
        updated_at: "2026-09-12T01:00:00Z",
      }]),
    });
  });
  await page.route("**/api/v1/review/changesets", async (route) => {
    await route.fulfill({ contentType: "application/json", body: "[]" });
  });

  await page.goto("/review/tasks");

  const status = page.locator("[data-review-task] .status-badge");
  await expect(status).toHaveAttribute("data-status", "changes_requested");
  await expect(status).toContainText("需修改");
  await expect(status.locator(".status-dot")).toHaveAttribute("aria-hidden", "true");
  await expect(page.getByRole("heading", { name: "核查任务", level: 1 })).toBeVisible();
  await expectVisibleFocus(page.getByRole("link", { name: "开始核查" }));
  await expectNoHorizontalPageOverflow(page);
});


test("admin import decisions keep form, primary, and danger actions keyboard-visible", async ({ page }) => {
  await page.route("**/api/v1/auth/session", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        user: {
          username: "admin.accessibility",
          display_name: "可访问性管理员",
          role: "admin",
          must_change_password: false,
        },
        csrf_token: "accessibility-csrf",
      }),
    });
  });
  await page.route("**/api/v1/admin/imports", async (route) => {
    await route.fulfill({ contentType: "application/json", body: "[]" });
  });
  await page.route("**/api/v1/admin/import-candidates", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([{
        id: "90000000-0000-4000-8000-000000000001",
        import_batch_id: "90000000-0000-4000-8000-000000000002",
        status: "imported_baseline",
        is_current: true,
        manifest: {
          source_fingerprint: "sha256:accessibility",
          counts: { corpus_papers: 1 },
          revision_count: 1,
          integrity: { dangling_entity_references: 0 },
          asset_linkage: {
            resolved_references: 1,
            unique_resolved_assets: 1,
            missing_references: 0,
            ambiguous_references: 0,
            corrupt_references: 0,
          },
        },
        decision: null,
        created_at: "2026-09-12T00:00:00Z",
      }]),
    });
  });

  await page.goto("/admin/imports");
  await expect(page.getByRole("heading", { name: "导入管理", level: 1 })).toBeVisible();
  const reason = page.getByLabel("审批原因");
  await reason.fill("键盘可访问性检查");
  await expectVisibleFocus(reason);
  await expectVisibleFocus(page.getByRole("button", { name: "批准" }));
  await expectVisibleFocus(page.getByRole("button", { name: "拒绝" }));
  await expectNoHorizontalPageOverflow(page);
});

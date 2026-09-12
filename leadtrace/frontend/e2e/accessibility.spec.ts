import { expect, test } from "@playwright/test";


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
  await submit.click();
  const alert = page.getByRole("alert");
  await expect(alert).toBeVisible();
  await expect(alert).not.toBeEmpty();
  await expect(alert.locator("[aria-hidden='true']")).toHaveCount(1);

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
        release: { id: "10000000-0000-4000-8000-000000000001", key: "r1", title: "R1", published_at: "2026-09-12T00:00:00Z" },
        metrics: {},
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
});

import { expect, test } from "@playwright/test";

import {
  startKetcherCspServer,
  type KetcherCspServer,
} from "./fixtures/ketcher-csp-server";

declare global {
  interface Window {
    ketcherHarness?: {
      ready: boolean;
      molfile: string;
      errors: string[];
    };
  }
}

let fixture: KetcherCspServer;

test.beforeAll(async () => {
  fixture = await startKetcherCspServer();
});

test.afterAll(async () => {
  await fixture.close();
});

test("real Ketcher imports SMILES and exports Molfile under its scoped CSP", async ({ page, request }) => {
  test.setTimeout(120_000);
  const cspErrors: string[] = [];
  const pageErrors: string[] = [];
  page.on("console", (message) => {
    if (
      message.type() === "error"
      && /content security policy|refused|unsafe-eval|worker-src|wasm/i.test(message.text())
    ) {
      cspErrors.push(message.text());
    }
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));

  const parentResponse = await request.get(`${fixture.origin}/test-parent.html`);
  const ketcherResponse = await request.get(`${fixture.origin}/ketcher.html`);
  expect(parentResponse.headers()["content-security-policy"]).toContain("script-src 'self';");
  expect(parentResponse.headers()["content-security-policy"]).toContain("frame-ancestors 'none'");
  expect(parentResponse.headers()["x-frame-options"]).toBe("DENY");
  expect(ketcherResponse.headers()["content-security-policy"]).toContain("script-src 'self' 'unsafe-eval'");
  expect(ketcherResponse.headers()["content-security-policy"]).toContain("worker-src 'self' blob:");
  expect(ketcherResponse.headers()["content-security-policy"]).toContain("frame-ancestors 'self'");
  expect(ketcherResponse.headers()["x-frame-options"]).toBe("SAMEORIGIN");

  await page.goto(`${fixture.origin}/test-parent.html`);
  await expect.poll(
    () => page.evaluate(() => window.ketcherHarness?.ready ?? false),
    { timeout: 90_000 },
  ).toBe(true);
  await expect.poll(
    () => page.evaluate(() => window.ketcherHarness?.molfile ?? ""),
    { timeout: 30_000 },
  ).not.toBe("");

  expect(await page.evaluate(() => window.ketcherHarness?.errors ?? [])).toEqual([]);
  expect(cspErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
});

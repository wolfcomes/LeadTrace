import { defineConfig, devices } from "@playwright/test";

const origin = process.env.PREVIEW_LIVE_ORIGIN;
if (!origin || !/^http:\/\/127\.(?:\d{1,3}\.){2}\d{1,3}:\d+$/.test(origin)) {
  throw new Error("Set PREVIEW_LIVE_ORIGIN to the running Preview's explicit IPv4 loopback HTTP origin");
}
new URL(origin); // Reject invalid addresses/ports before opening a browser.
if (!process.env.PREVIEW_LIVE_CREDENTIALS_FILE) {
  throw new Error("Set PREVIEW_LIVE_CREDENTIALS_FILE to its protected credentials.json");
}

export default defineConfig({
  testDir: "./e2e",
  testMatch: "ai-prefill-preview-live.spec.ts",
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 20_000 },
  reporter: "list",
  outputDir: process.env.PREVIEW_LIVE_OUTPUT_DIR ?? "test-results/preview-live",
  use: {
    baseURL: origin,
    // Traces/video can retain credentials and session cookies. Capture only
    // explicitly requested post-login scientific views in the test.
    trace: "off",
    video: "off",
    screenshot: "off",
    ...devices["Desktop Chrome"],
  },
});

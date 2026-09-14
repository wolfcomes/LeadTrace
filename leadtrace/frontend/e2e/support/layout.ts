import { expect, type Page } from "@playwright/test";


const responsiveViewports = [
  { width: 1440, height: 900 },
  { width: 1024, height: 768 },
  { width: 390, height: 844 },
] as const;

export async function expectNoHorizontalPageOverflow(page: Page): Promise<void> {
  const originalViewport = page.viewportSize();
  try {
    for (const viewport of responsiveViewports) {
      await page.setViewportSize(viewport);
      await expect.poll(() => page.evaluate(() => ({
        documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        bodyOverflow: document.body.scrollWidth - document.body.clientWidth,
      }))).toEqual({ documentOverflow: 0, bodyOverflow: 0 });
    }
  } finally {
    if (originalViewport) await page.setViewportSize(originalViewport);
  }
}

import { expect, test } from '@playwright/test';

const cases = [
  ['/admin/papers', '/api/v2/admin/papers'],
  ['/admin/submissions', '/api/v2/admin/submissions'],
  ['/admin/files', '/api/v1/admin/files'],
  ['/admin/ai-tasks', '/api/v2/admin/ai-tasks'],
] as const;

for (const [path, endpoint] of cases) {
  test(`article filters compose, survive reload and reset: ${path}`, async ({ page }) => {
    const requests: URL[] = [];
    await page.route('**/api/**', async route => {
      const url = new URL(route.request().url());
      if (!url.pathname.startsWith('/api/')) return route.continue();
      const reply = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
      if (url.pathname === '/api/preview/environment') return reply({}, 404);
      if (url.pathname.endsWith('/auth/session')) return reply({ user: { username: 'admin', display_name: 'Admin', role: 'admin', must_change_password: false }, csrf_token: 'synthetic' });
      if (url.pathname.endsWith('/filter-options')) return reply({ journals: ['Journal of Medicinal Chemistry', 'Example Journal'], years: [2023, 2024], volumes: ['67', 'S1'], issues: ['5', 'S2'] });
      if (url.pathname === endpoint) {
        requests.push(url);
        if (endpoint.endsWith('/files')) return reply([]);
        if (endpoint.endsWith('/ai-tasks')) return reply({ items: [], total: 0, settings: { max_concurrent: 4 }, worker: { online: true, last_seen_at: null }, presets: [] });
        if (endpoint.endsWith('/submissions')) return reply({ items: [], total: 0 });
        return reply({ items: [], total: 0, limit: Number(url.searchParams.get('limit') || 20), offset: Number(url.searchParams.get('offset') || 0) });
      }
      return reply({ detail: 'Synthetic endpoint unavailable' }, 404);
    });
    await page.goto(path);
    const form = page.locator('[data-paper-filters]');
    await expect(form).toBeVisible();
    await form.locator('[name=journal]').fill('Journal of Medicinal Chemistry');
    await form.locator('[name=year_from]').fill('2023');
    await form.locator('[name=year_to]').fill('2024');
    await form.locator('[name=volume]').fill('67');
    await form.locator('[name=issue]').fill('5');
    await form.locator('[name=assignment_status]').selectOption('assigned');
    await form.locator('[name=prefill_status]').selectOption('succeeded');
    await form.locator('button[type=submit]').click();
    await expect.poll(() => requests.at(-1)?.searchParams.get('prefill_status')).toBe('succeeded');
    for (const [key, value] of Object.entries({ journal: 'Journal of Medicinal Chemistry', year_from: '2023', year_to: '2024', volume: '67', issue: '5', assignment_status: 'assigned', prefill_status: 'succeeded' })) {
      expect(requests.at(-1)?.searchParams.get(key)).toBe(value);
      expect(new URL(page.url()).searchParams.get(key)).toBe(value);
    }
    await page.reload();
    await expect(form.locator('[name=volume]')).toHaveValue('67');
    await expect(form.locator('[name=prefill_status]')).toHaveValue('succeeded');
    if (path === '/admin/papers') {
      await page.setViewportSize({ width: 390, height: 844 });
      await expect(form).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
      expect(overflow).toBe(false);
      await page.screenshot({ path: process.env.FILTER_SCREENSHOT_DIR ? `${process.env.FILTER_SCREENSHOT_DIR}/catalog-mobile.png` : 'test-results/catalog-filters-mobile.png', fullPage: true });
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.screenshot({ path: process.env.FILTER_SCREENSHOT_DIR ? `${process.env.FILTER_SCREENSHOT_DIR}/catalog-desktop.png` : 'test-results/catalog-filters-desktop.png', fullPage: true });
    }
    await form.locator('[data-reset-filters]').click();
    await expect.poll(() => requests.at(-1)?.searchParams.has('journal')).toBe(false);
    await expect(form.locator('[name=journal]')).toHaveValue('');
    expect(new URL(page.url()).searchParams.has('prefill_status')).toBe(false);
  });
}

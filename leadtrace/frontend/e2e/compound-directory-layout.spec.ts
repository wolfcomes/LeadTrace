import { expect, test } from '@playwright/test';

const id = (n: number) => `91000000-0000-4000-8000-${String(n).padStart(12, '0')}`;

for (const preview of [false, true]) {
  test(`compound directory stays below navigation (${preview ? 'Preview' : 'ordinary'})`, async ({ page }) => {
    const paper = id(1), workspaceId = id(2);
    const compounds = Array.from({ length: 40 }, (_, i) => ({
      id: id(100 + i), paper_id: paper, workspace_id: workspaceId,
      compound_label: String(i + 1), display_name: `Synthetic compound ${i + 1}`,
      description: null, sort_order: i, created_by_kind: 'ai', review_hint: i === 1 ? 'Synthetic hint' : null,
    }));
    const sections = ['bibliography', 'compounds', 'structures', 'lineages', 'edge_evidence', 'activities']
      .map(section_key => ({ section_key, state: 'pending', note: null }));
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (!path.startsWith('/api/')) return route.continue();
      const reply = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
      if (path === '/api/preview/environment') return reply(preview ? { environment: 'preview', instance_id: id(9) } : {}, preview ? 200 : 404);
      if (path.endsWith('/auth/session')) return reply({ user: { username: 'reviewer', display_name: 'Test reviewer', role: 'reviewer', must_change_password: false }, csrf_token: 'test' });
      if (path === `/api/v2/workspaces/${workspaceId}`) return reply({
        id: workspaceId, review_task_id: id(3), assigned_reviewer_id: id(4), state: 'editing', version: 1, task_status: 'assigned',
        bibliography: { paper_id: paper, paper_key: 'SYNTHETIC-LAYOUT', title: 'Synthetic directory scrolling example', journal: 'Test', publication_year: 2026, volume: '1', issue: '1', doi: null },
        source: { asset_id: id(6), source_root_key: 'source_pdfs', source_key: 'synthetic.pdf', sha256: 'a'.repeat(64), page_count: 1 }, sections,
      });
      if (path.endsWith('/review-progress')) return reply({ workspace_id: workspaceId, workspace_version: 1, tracking_started: false, items: [], sections: sections.map(s => ({ ...s, total: 0, viewed: 0, complete: false })) });
      if (path.endsWith('/compound-highlights')) return reply({ workspace_id: workspaceId, workspace_version: 1, total: 2, items: compounds.slice(0, 2).map((c, i) => ({ id: id(500 + i), compound_id: c.id, paper_id: paper, workspace_id: workspaceId, evidence_id: id(600), role: 'study_start', scope: 'paper', rationale: 'Synthetic layout fixture', review_status: 'draft', created_by_kind: 'ai' })) });
      if (path.endsWith('/structure')) return reply({ workspace_version: 1, structure: null });
      if (path.endsWith('/compounds')) return reply({ workspace_id: workspaceId, workspace_version: 1, items: compounds, total: compounds.length });
      return reply({ workspace_id: workspaceId, workspace_version: 1, items: [], total: 0 });
    });
    await page.goto(`/review/papers/${paper}?workspace=${workspaceId}&tab=compounds`);
    const directory = page.locator('.compound-list-panel');
    const tabs = page.locator('[data-workspace-tabs]');
    await expect(directory.locator('[data-compound-row]')).toHaveCount(40);
    await expect(page.locator('[data-preview-environment]')).toHaveCount(preview ? 1 : 0);
    await expect(directory.locator('.highlight-badges')).toHaveCount(2);
    await page.evaluate(() => document.fonts.ready);
    // Represent a long structure/activity editor without introducing scientific fixtures.
    await page.locator('.compound-detail-panel').evaluate(el => { (el as HTMLElement).style.minHeight = '2400px'; });
    for (const locale of ['zh-CN', 'en']) {
      await page.locator('[data-language-switch]').selectOption(locale);
      for (const width of [1440, 1024, 901]) {
        await page.setViewportSize({ width, height: 900 });
        await directory.evaluate(el => { el.scrollTop = 0; });
        await page.evaluate(() => window.scrollTo(0, 1050));
        await expect.poll(async () => {
          const listBox = (await directory.boundingBox())!, tabBox = (await tabs.boundingBox())!;
          return listBox.y - tabBox.y - tabBox.height;
        }, { message: `${locale}, ${width}px: first row must clear sticky tabs` }).toBeGreaterThanOrEqual(8);
        const firstRow = directory.locator('[data-compound-row]').first();
        const badgeBox = (await firstRow.locator('.highlight-badges').boundingBox())!;
        const nameBox = (await firstRow.locator('button').first().boundingBox())!;
        expect(badgeBox.y).toBeGreaterThanOrEqual(nameBox.y + nameBox.height);
        const listBox = (await directory.boundingBox())!;
        expect(listBox.y + listBox.height).toBeLessThanOrEqual(900 - 20);
        for (const button of await directory.locator('[data-compound-row]').first().locator('button').all()) {
          // Trial checks actual hit targets without editing or deleting records.
          await button.click({ trial: true });
        }
        await directory.hover();
        await page.mouse.wheel(0, 500);
        await expect.poll(() => directory.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
      }
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(directory).toHaveCSS('position', 'static');
    expect(await directory.evaluate(el => el.getBoundingClientRect().height)).toBeLessThanOrEqual(260);
  });
}

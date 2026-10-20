import { expect, test } from '@playwright/test';

const id = (n: number) => `93000000-0000-4000-8000-${String(n).padStart(12, '0')}`;

test('confirms a sourced absence, then completes the same Compound without losing its Activity', async ({ page }) => {
  const paper = id(1), workspace = id(2), compound = id(3), structureId = id(4);
  let version = 1;
  let structure: Record<string, unknown> = {
    id: structureId, paper_id: paper, workspace_id: workspace, compound_id: compound,
    smiles: null, molfile: null, canonical_smiles: null, inchi: null, inchikey: null,
    depiction_asset_id: null, status: 'draft', input_method: 'ai_prefill',
    availability: 'not_checked', availability_note: 'Synthetic SI was not provided.',
    identity_source: 'Synthetic Table 1, compound C1', checked_sources: 'Main text checked; SI unavailable.',
  };
  const activity = {
    id: id(5), paper_id: paper, workspace_id: workspace, compound_id: compound,
    evidence_id: null, assay_name: 'Synthetic potency', metric: 'IC50', operator: '=',
    value: '12', unit: 'nM', context: null, review_hint: null, sort_order: 0,
  };
  const writes: Record<string, unknown>[] = [];
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/v*/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    const reply = (body: unknown, status = 200) => route.fulfill({
      status, contentType: 'application/json', body: JSON.stringify(body),
    });
    if (path === '/api/v1/auth/session') return reply({
      user: { username: 'reviewer', display_name: 'Synthetic reviewer', role: 'reviewer', must_change_password: false },
      csrf_token: 'synthetic-csrf',
    });
    if (path === `/api/v2/workspaces/${workspace}`) return reply({
      id: workspace, review_task_id: id(6), assigned_reviewer_id: id(7), state: 'editing',
      version, task_status: 'assigned',
      bibliography: { paper_id: paper, paper_key: 'SYNTHETIC-AVAILABILITY', title: 'Synthetic availability fixture', journal: 'Fixtures', publication_year: 2026, volume: '1', issue: '1', doi: null },
      source: { asset_id: id(8), source_root_key: 'source_pdfs', source_key: 'synthetic.pdf', sha256: 'a'.repeat(64), page_count: 1 },
      sections: ['bibliography', 'compounds', 'structures', 'lineages', 'edge_evidence', 'activities'].map(section_key => ({ section_key, state: 'pending', note: null })),
    });
    if (path.endsWith('/compounds')) return reply({
      workspace_id: workspace, workspace_version: version, total: 1,
      items: [{ id: compound, paper_id: paper, workspace_id: workspace, compound_label: 'C1', display_name: 'Synthetic C1', description: null, sort_order: 0, created_by_kind: 'ai' }],
      structure_counts: { total: 1, available: structure.canonical_smiles ? 1 : 0, not_checked: structure.canonical_smiles ? 0 : 1, not_reported: 0, unresolved: 0, confirmed: structure.status === 'reviewer_confirmed' ? 1 : 0 },
    });
    if (path === `/api/v2/compounds/${compound}/structure`) {
      if (request.method() === 'PUT') {
        const { expected_workspace_version, ...body } = request.postDataJSON();
        expect(expected_workspace_version).toBe(version);
        writes.push(body);
        version++;
        structure = { ...structure, ...body, canonical_smiles: body.smiles ?? null, inchi: body.smiles ? 'Synthetic InChI' : null };
      }
      return reply({ workspace_version: version, structure });
    }
    if (path.endsWith('/activities')) return reply({ compound_id: compound, workspace_version: version, items: [activity], total: 1 });
    if (path.endsWith('/source-images')) return reply({ compound_id: compound, workspace_version: version, items: [], total: 0 });
    if (path.endsWith('/edit-history')) return reply({ workspace_version: version, undo_action: null, redo_action: null });
    if (path.endsWith('/review-progress')) return reply({ workspace_id: workspace, workspace_version: version, tracking_started: false, items: [], sections: [] });
    if (path.endsWith('/evidence') || path.endsWith('/compound-highlights')) return reply({ workspace_id: workspace, workspace_version: version, items: [], total: 0 });
    return reply({}, 404);
  });

  await page.goto(`/review/papers/${paper}?workspace=${workspace}&tab=compounds`);
  await expect(page.locator('[data-structure-availability]')).toContainText('来源检查未完成');
  await expect(page.locator('[data-structure-status]')).toHaveText('Draft');
  await expect(page.locator('[data-structure-counts]')).toContainText('条目 1 · 可用结构 0');
  await expect(page.locator('[data-activity-row]')).toHaveCount(1);
  await expect(page.locator('[data-confirm-structure]')).toBeDisabled();
  await page.locator('[data-availability-note]').fill('Synthetic main text checked; supplementary structure still unavailable.');
  await expect(page.locator('[data-confirm-absence]')).toBeDisabled();
  await page.locator('[data-save-absence]').click();
  await expect(page.locator('[data-confirm-absence]')).toBeEnabled();
  await page.locator('[data-confirm-absence]').click();
  await expect(page.locator('[data-structure-status]')).toHaveText('Reviewer 已确认');
  await page.reload();
  await expect(page.locator('[data-availability-note]')).toHaveValue('Synthetic main text checked; supplementary structure still unavailable.');
  await expect(page.locator('[data-structure-status]')).toHaveText('Reviewer 已确认');

  await page.locator('[data-smiles-input]').fill('CCO');
  await page.locator('[data-save-structure]').click();
  await expect(page.locator('[data-structure-status]')).toHaveText('Draft');
  await expect(page.locator('[data-structure-availability]')).toContainText('有可用结构');
  await expect(page.locator('[data-structure-counts]')).toContainText('条目 1 · 可用结构 1');
  await expect(page.locator('[data-activity-row]')).toHaveCount(1);
  await expect(page.locator('[data-confirm-structure]')).toBeEnabled();
  expect(structure.id).toBe(structureId);
  expect(structure.compound_id).toBe(compound);
  expect(writes.map(body => body.status)).toEqual(['draft', 'reviewer_confirmed', 'draft']);
  expect(writes[2]).toMatchObject({ availability: 'available', availability_note: null, identity_source: null, checked_sources: null });
  expect(errors).toEqual([]);
});

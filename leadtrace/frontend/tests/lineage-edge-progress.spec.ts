import { flushPromises } from '@vue/test-utils';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { compounds, edges, ids, installReviewer, lineages, mountWorkspace, response, workspace } from './paper-science-v2-fixtures';

beforeEach(installReviewer);
afterEach(() => vi.unstubAllGlobals());

async function setup(evidenceFails = false, evidenceGate?: Promise<void>, entity?: string, evidenceVersion = 1) {
  const ws = workspace();
  ws.sections = ws.sections.map(s => ({ ...s, state: 'pending' as const }));
  const items = [
    ...lineages.map(l => ({ kind: 'lineage', entity_id: l.id, section_key: 'lineages', label: l.lineage_label, signature: 'a'.repeat(64), viewed: false })),
    ...edges.map(e => ({ kind: 'edge', entity_id: e.id, section_key: 'edge_evidence', label: '1 → 2', signature: 'b'.repeat(64), viewed: false })),
  ];
  const writes: any[] = [];
  const progress = () => ({ workspace_id: ws.id, workspace_version: ws.version, tracking_started: items.some(i => i.viewed), items,
    sections: [{ section_key: 'lineages', total: items.length, viewed: items.filter(i => i.viewed).length,
      complete: items.every(i => i.viewed), state: 'pending', note: null }] });
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), 'http://test').pathname;
    if (path.endsWith('/review-progress')) return response(progress());
    if (path.endsWith('/views')) {
      const body = JSON.parse(String(init?.body)); writes.push(body);
      const item = items.find(i => i.kind === body.kind && i.entity_id === body.entity_id)!;
      item.viewed = body.viewed; return response(progress());
    }
    if (path.endsWith('/compounds')) return response({ workspace_id: ws.id, workspace_version: 1, items: compounds, total: compounds.length });
    if (path.endsWith('/lineages')) return response({ workspace_id: ws.id, workspace_version: 1, items: lineages, total: lineages.length });
    if (path.endsWith('/evidence') || path.endsWith('/evidence-links')) {
      if (evidenceFails) throw new Error('Evidence unavailable');
      await evidenceGate;
      return response({ ...(path.endsWith('/evidence-links') ? { edge_id: path.split('/')[4] } : { workspace_id: ws.id }), workspace_version: evidenceVersion, items: [], total: 0 });
    }
    return response(ws);
  }));
  return { ...(await mountWorkspace('lineages', entity)), writes, items };
}

it('shows separate Lineage and Edge progress and completes only after both sets are viewed', async () => {
  const { wrapper, writes } = await setup();
  const status = wrapper.get('[data-section-key="lineages"]');
  expect(status.get('[data-view-progress="lineage"]').text()).toContain(`0 / ${lineages.length}`);
  expect(status.get('[data-view-progress="edge"]').text()).toContain(`0 / ${edges.length}`);
  for (const l of lineages) {
    await wrapper.get(`[data-lineage-id="${l.id}"] > button`).trigger('click');
    await flushPromises();
  }
  expect(writes.every(w => w.kind === 'lineage')).toBe(true);
  expect(status.attributes('data-state')).toBe('pending');
  for (const l of lineages) {
    await wrapper.get(`[data-lineage-id="${l.id}"] > button`).trigger('click');
    await flushPromises();
    for (const e of l.edges) {
      await wrapper.get(`[data-edge-id="${e.id}"] [data-open-edge]`).trigger('click');
      await flushPromises();
      await wrapper.get('[data-return-lineage]').trigger('click');
      await flushPromises();
    }
  }
  expect(writes.filter(w => w.kind === 'edge')).toHaveLength(edges.length);
  expect(status.attributes('data-state')).toBe('completed');
  expect(status.get('[data-view-progress="edge"]').text()).toContain(`${edges.length} / ${edges.length}`);
  wrapper.unmount();
});

it('does not mark an Edge viewed when its evidence failed to load', async () => {
  const { wrapper, writes } = await setup(true);
  await wrapper.get(`[data-edge-id="${edges[0]!.id}"] [data-open-edge]`).trigger('click');
  await flushPromises();
  expect(writes.filter(w => w.kind === 'edge')).toHaveLength(0);
  wrapper.unmount();
});


it('records a directly addressed Edge only after its evidence loads', async () => {
  let finish!: () => void;
  const gate = new Promise<void>(resolve => { finish = resolve; });
  const { wrapper, writes } = await setup(false, gate, edges[0]!.id);
  expect(writes).toHaveLength(0);
  finish(); await flushPromises();
  expect(writes).toEqual([expect.objectContaining({ kind: 'edge', entity_id: edges[0]!.id, viewed: true })]);
  await wrapper.get('.lineage-main-panel > .view-state button').trigger('click');
  await flushPromises();
  expect(writes.at(-1)).toMatchObject({ kind: 'edge', viewed: false });
  expect(writes).toHaveLength(2);
  wrapper.unmount();
});

it('does not record delayed Edge viewing after leaving the Lineage tab', async () => {
  let finish!: () => void;
  const gate = new Promise<void>(resolve => { finish = resolve; });
  const { wrapper, writes, router } = await setup(false, gate, edges[0]!.id);
  await router.replace({ path: router.currentRoute.value.path, query: { ...router.currentRoute.value.query, tab: 'bibliography' } });
  await flushPromises();
  finish(); await flushPromises();
  expect(writes).toHaveLength(0);
  wrapper.unmount();
});

it('does not mark an Edge viewed from mismatched evidence and graph versions', async () => {
  const { wrapper, writes } = await setup(false, undefined, edges[0]!.id, 2);
  expect(writes).toHaveLength(0);
  wrapper.unmount();
});

it('does not record a delayed Edge view after switching back to the graph view', async () => {
  let finish!: () => void;
  const gate = new Promise<void>(resolve => { finish = resolve; });
  const { wrapper, writes } = await setup(false, gate, edges[0]!.id);
  await wrapper.get('[data-lineage-view-tab="graph"]').trigger('click');
  finish(); await flushPromises();
  expect(writes).toHaveLength(0);
  wrapper.unmount();
});

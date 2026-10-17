import { flushPromises } from '@vue/test-utils';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useAuthStore } from '../src/auth/store';
import { compounds, ids, installReviewer, lineages, members, mountWorkspace, response, workspace } from './paper-science-v2-fixtures';

beforeEach(installReviewer);
afterEach(() => vi.unstubAllGlobals());

function installData(contentVersion = 1) {
  const writes: { path: string; body: unknown }[] = [];
  const items = lineages.map(l => ({ kind: 'lineage', entity_id: l.id, section_key: 'lineages', label: l.lineage_label, signature: 'a'.repeat(64), viewed: false }));
  const catalog = [
    { ...lineages[0], lineage_type: 'sar', members: members.slice(0, 2), edges: [] },
    { ...lineages[1], lineage_type: 'synthesis', members: [{ ...members[2], lineage_id: ids.lineages[1] }], edges: [] },
  ];
  const progress = () => ({ workspace_id: ids.workspace, workspace_version: 1, tracking_started: items.some(i => i.viewed), items, sections: [] });
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), 'http://test').pathname;
    if (init?.method && init.method !== 'GET') writes.push({ path, body: JSON.parse(String(init.body)) });
    if (path.endsWith('/review-progress')) return response(progress());
    if (path.endsWith('/views')) { const body = JSON.parse(String(init?.body)); items.find(i => i.entity_id === body.entity_id)!.viewed = body.viewed; return response(progress()); }
    if (path.endsWith('/compounds')) return response({ workspace_id: ids.workspace, workspace_version: contentVersion, items: compounds, total: compounds.length });
    if (path.endsWith('/lineages')) return response({ workspace_id: ids.workspace, workspace_version: 1, items: catalog, total: catalog.length });
    return response(workspace());
  }));
  return writes;
}

it('searches names across groups and focuses the matching graph node without recording viewed', async () => {
  const writes = installData();
  const { wrapper, router } = await mountWorkspace('lineages');
  await wrapper.get('[data-lineage-compound-search]').setValue('  compound 3  ');
  const matches = wrapper.findAll('[data-lineage-search-result]');
  expect(matches).toHaveLength(1);
  expect(matches[0]!.text()).toContain('Series B');
  await matches[0]!.trigger('click');
  await flushPromises();
  expect(wrapper.get('[data-lineage-group="synthesis"]').attributes('aria-pressed')).toBe('true');
  expect(router.currentRoute.value.query.entity).toBe(ids.lineages[1]);
  expect(wrapper.get('[data-lineage-view="graph"]').isVisible()).toBe(true);
  expect((wrapper.get('[data-graph-locate]').element as HTMLSelectElement).value).toBe(ids.compounds[2]);
  expect(writes).toHaveLength(0);
  wrapper.unmount();
});

it('filters current members and available add-member choices by label or name', async () => {
  installData();
  const { wrapper } = await mountWorkspace('lineages');
  await wrapper.get('[data-lineage-view-tab="compounds"]').trigger('click');
  await wrapper.get('[data-member-search]').setValue('COMPOUND 2');
  expect(wrapper.findAll('.member-row')).toHaveLength(1);
  expect(wrapper.get('.member-row').text()).toContain('C2');
  await wrapper.get('[data-member-add-search]').setValue('c4');
  const choices = wrapper.findAll('[data-member-compound-select] option');
  expect(choices).toHaveLength(1);
  expect(choices[0]!.attributes('value')).toBe(ids.compounds[3]);
  expect((wrapper.get('[data-member-compound-select]').element as HTMLSelectElement).value).toBe(ids.compounds[3]);
  await wrapper.get('[data-member-add-search]').setValue('missing');
  expect(wrapper.findAll('[data-member-compound-select] option')).toHaveLength(0);
  expect(wrapper.get('.member-editor button[type="submit"]').attributes('disabled')).toBeDefined();
  wrapper.unmount();
});

it('explicitly marks the current graph viewed without opening an Edge or changing scientific status', async () => {
  const writes = installData();
  const { wrapper } = await mountWorkspace('lineages');
  expect(writes).toHaveLength(0);
  await wrapper.get('[data-mark-lineage-viewed]').trigger('click');
  await flushPromises();
  expect(writes).toEqual([{ path: `/api/v2/workspaces/${ids.workspace}/views`, body: { kind: 'lineage', entity_id: ids.lineages[0], signature: 'a'.repeat(64), viewed: true } }]);
  expect(wrapper.get('[data-lineage-view="graph"]').isVisible()).toBe(true);
  expect(wrapper.get('[data-mark-lineage-viewed]').attributes('disabled')).toBeDefined();
  wrapper.unmount();
});

it('disables explicit viewed when loaded content versions disagree', async () => {
  const writes = installData(2);
  const { wrapper } = await mountWorkspace('lineages');
  expect(wrapper.get('[data-mark-lineage-viewed]').attributes('disabled')).toBeDefined();
  await wrapper.get('[data-mark-lineage-viewed]').trigger('click');
  expect(writes).toHaveLength(0);
  wrapper.unmount();
});

it('keeps search available to read-only reviewers while disabling viewed writes', async () => {
  const writes = installData();
  useAuthStore().acceptSession({ user: { username: 'admin', display_name: 'Admin', role: 'admin', must_change_password: false }, csrf_token: 'admin-csrf' });
  const { wrapper } = await mountWorkspace('lineages');
  expect(wrapper.get('[data-mark-lineage-viewed]').attributes('disabled')).toBeDefined();
  await wrapper.get('[data-lineage-compound-search]').setValue('c3');
  await wrapper.get('[data-lineage-search-result]').trigger('click');
  await flushPromises();
  expect((wrapper.get('[data-graph-locate]').element as HTMLSelectElement).value).toBe(ids.compounds[2]);
  expect(writes).toHaveLength(0);
  wrapper.unmount();
});

it('shows an empty search result instead of selecting an unrelated Lineage', async () => {
  installData();
  const { wrapper } = await mountWorkspace('lineages');
  await wrapper.get('[data-lineage-compound-search]').setValue('unavailable compound');
  expect(wrapper.findAll('[data-lineage-search-result]')).toHaveLength(0);
  expect(wrapper.get('.lineage-search-results').text()).toContain('没有匹配的 Lineage 成员');
  expect(wrapper.get('[data-lineage-group="sar"]').attributes('aria-pressed')).toBe('true');
  wrapper.unmount();
});

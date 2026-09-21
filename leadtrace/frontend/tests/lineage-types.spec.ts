import { flushPromises } from '@vue/test-utils';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { lineageRecordSchema } from '../src/v2/types';
import { compounds, edges, ids, installReviewer, lineages, mountWorkspace, response, workspace } from './paper-science-v2-fixtures';

let records: Array<Record<string, unknown>>;
let writes: Array<Record<string, unknown>>;
beforeEach(() => {
  installReviewer(); writes = [];
  records = [
    { ...lineages[0], lineage_type: 'synthesis', lineage_label: 'Compound synthesis' },
    { ...lineages[1], lineage_type: 'sar', lineage_label: 'R1 SAR' },
    { ...lineages[1], id: ids.lineages[2], lineage_label: 'Legacy series' },
  ];
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), 'http://test').pathname;
    if (init?.method === 'POST' || init?.method === 'PATCH') {
      const body = JSON.parse(String(init.body)); writes.push(body);
      const record = init.method === 'POST' ? { ...lineages[1], id: '30000000-0000-4000-8000-000000000099', ...body } : { ...records.find(r => path.endsWith(String(r.id))), ...body };
      delete record.expected_workspace_version;
      records = init.method === "POST" ? [...records, record] : records.map(item => item.id === record.id ? record : item);
      return response({ lineage: record, workspace_version: 2 });
    }
    if (path.endsWith('/compounds')) return response({ workspace_id: ids.workspace, workspace_version: 1, items: compounds, total: compounds.length });
    if (path.endsWith('/lineages')) return response({ workspace_id: ids.workspace, workspace_version: 1, items: records, total: records.length });
    if (path.endsWith('/evidence')) return response({ workspace_id: ids.workspace, workspace_version: 1, items: [], total: 0 });
    if (path.endsWith('/evidence-links')) return response({ edge_id: path.split('/')[4], workspace_version: 1, items: [], total: 0 });
    if (path.endsWith('/structure')) return response({ structure: null, workspace_version: 1 });
    return response(workspace());
  }));
});
afterEach(() => vi.unstubAllGlobals());
it('normalizes old Lineage records without inventing a scientific category', () => {
  expect(lineageRecordSchema.parse(lineages[0]).lineage_type).toBe('unspecified');
});
it('defaults to SAR and separates synthesis and unclassified records', async () => {
  const { wrapper } = await mountWorkspace('lineages');
  expect(wrapper.get('[data-lineage-group="sar"]').attributes('aria-pressed')).toBe('true');
  expect(wrapper.findAll('[data-lineage-card]').map(c => c.attributes('data-lineage-id'))).toEqual([ids.lineages[1]]);
  await wrapper.get('[data-lineage-group="synthesis"]').trigger('click'); await flushPromises();
  expect(wrapper.findAll('[data-lineage-card]').map(c => c.attributes('data-lineage-id'))).toEqual([ids.lineages[0]]);
  await wrapper.get('[data-lineage-group="unspecified"]').trigger('click'); await flushPromises();
  expect(wrapper.findAll('[data-lineage-card]').map(c => c.attributes('data-lineage-id'))).toEqual([ids.lineages[2]]);
  wrapper.unmount();
});
it('opens a synthesis Edge deep link and follows groups through history', async () => {
  const { wrapper, router } = await mountWorkspace('lineages', edges[0]!.id);
  expect(wrapper.get('[data-lineage-group="synthesis"]').attributes('aria-pressed')).toBe('true');
  expect(wrapper.get('[data-edge-detail]').text()).toContain('反应前体');
  await wrapper.get('[data-lineage-group="sar"]').trigger('click'); await flushPromises();
  expect(wrapper.find('[data-edge-detail]').exists()).toBe(false);
  router.back(); await new Promise(resolve => setTimeout(resolve, 0)); await flushPromises();
  expect(wrapper.get('[data-lineage-group="synthesis"]').attributes('aria-pressed')).toBe('true');
  expect(wrapper.get('[data-edge-detail]').attributes('data-selected-edge-id')).toBe(edges[0]!.id);
  wrapper.unmount();
});
it('submits an explicit type on create and moves edited Lineages to the new group', async () => {
  const { wrapper } = await mountWorkspace('lineages');
  await wrapper.get('[data-add-lineage]').trigger('click');
  await wrapper.get('[data-lineage-label-input]').setValue('New route');
  await wrapper.get('[data-lineage-type-input]').setValue('synthesis');
  await wrapper.get('[data-save-lineage]').trigger('click'); await flushPromises();
  expect(writes[0]).toMatchObject({ lineage_type: 'synthesis', lineage_label: 'New route' });
  expect(wrapper.get('[data-lineage-group="synthesis"]').attributes('aria-pressed')).toBe('true');
  await wrapper.get('[data-lineage-id="30000000-0000-4000-8000-000000000099"] [data-edit-lineage]').trigger('click');
  await wrapper.get('[data-edit-lineage-type]').setValue('sar');
  await wrapper.get('[data-save-lineage-edit]').trigger('click'); await flushPromises();
  expect(writes[1]).toMatchObject({ lineage_type: 'sar' });
  expect(wrapper.get('[data-lineage-group="sar"]').attributes('aria-pressed')).toBe('true');
  wrapper.unmount();
});
it('shows an empty group without a stale graph and restores the default group through history', async () => {
  records = records.filter(r => r.lineage_type !== undefined);
  const { wrapper, router } = await mountWorkspace('lineages');
  await wrapper.get('[data-lineage-group="synthesis"]').trigger('click'); await flushPromises();
  router.back(); await new Promise(resolve => setTimeout(resolve, 0)); await flushPromises();
  expect(wrapper.get('[data-lineage-group="sar"]').attributes('aria-pressed')).toBe('true');
  await wrapper.get('[data-lineage-group="unspecified"]').trigger('click'); await flushPromises();
  expect(wrapper.get('[data-lineage-group="unspecified"]').attributes('aria-pressed')).toBe('true');
  expect(wrapper.find('[data-lineage-graph]').exists()).toBe(false);
  expect(wrapper.text()).toContain('当前分类尚无 Lineage');
  wrapper.unmount();
});

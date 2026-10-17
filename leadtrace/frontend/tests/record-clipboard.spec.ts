import { flushPromises } from '@vue/test-utils';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { compounds, ids, installReviewer, lineages, mountWorkspace, response, workspace } from './paper-science-v2-fixtures';

beforeEach(installReviewer);
afterEach(() => vi.unstubAllGlobals());

function installData() {
  const writes: { path: string; body: any }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), 'http://test').pathname;
    if (init?.method === 'POST') {
      writes.push({path, body: JSON.parse(String(init.body))});
      if (path.includes('/clipboard/')) return response({ entity_id: '30000000-0000-4000-8000-000000000099', workspace_version: 2 }, 201);
    }
    if (path.endsWith('/compounds')) return response({workspace_id: ids.workspace, workspace_version: 1, items: compounds, total: compounds.length});
    if (path.endsWith('/lineages')) return response({workspace_id: ids.workspace, workspace_version: 1, items: lineages, total: lineages.length});
    return response(workspace());
  }));
  return writes;
}

it('pastes a Compound from a blank identity preview, blocking duplicate labels but only warning on duplicate names', async () => {
  const writes = installData();
  const { wrapper } = await mountWorkspace('compounds');
  await wrapper.get('[data-copy-record]').trigger('click');
  await wrapper.get('[data-paste-record]').trigger('click');
  expect((wrapper.get('[data-paste-label]').element as HTMLInputElement).value).toBe('');
  expect((wrapper.get('[data-paste-name]').element as HTMLInputElement).value).toBe('');
  expect(wrapper.get('[data-confirm-paste]').attributes('disabled')).toBeDefined();
  await wrapper.get('[data-paste-label]').setValue('C1');
  expect(wrapper.get('[data-confirm-paste]').attributes('disabled')).toBeDefined();
  expect(wrapper.get('[data-clipboard-label-warning]').text()).toContain('编号');
  await wrapper.get('[data-paste-label]').setValue('C5');
  await wrapper.get('[data-paste-name]').setValue('Compound 1');
  expect(wrapper.find('[data-clipboard-name-warning]').exists()).toBe(true);
  expect(wrapper.get('[data-confirm-paste]').attributes('disabled')).toBeUndefined();
  await wrapper.get('[data-paste-preview]').trigger('submit');
  await flushPromises();
  expect(writes).toEqual([{path: `/api/v2/workspaces/${ids.workspace}/clipboard/compound`, body: {source_id: ids.compounds[0], expected_workspace_version: 1, label: 'C5', display_name: 'Compound 1'}}]);
  wrapper.unmount();
});

it('pastes a Lineage with a blank label and allows a warned duplicate label', async () => {
  const writes = installData();
  const {wrapper} = await mountWorkspace('lineages');
  await wrapper.get('[data-copy-record]').trigger('click');
  await wrapper.get('[data-paste-record]').trigger('click');
  expect((wrapper.get('[data-paste-label]').element as HTMLInputElement).value).toBe('');
  expect(wrapper.find('[data-paste-name]').exists()).toBe(false);
  await wrapper.get('[data-paste-label]').setValue('Series A');
  expect(wrapper.find('[data-clipboard-label-warning]').exists()).toBe(true);
  expect(wrapper.get('[data-confirm-paste]').attributes('disabled')).toBeUndefined();
  await wrapper.get('[data-paste-preview]').trigger('submit');
  await flushPromises();
  expect(writes).toEqual([{path: `/api/v2/workspaces/${ids.workspace}/clipboard/lineage`, body: {source_id: ids.lineages[0], expected_workspace_version: 1, label: 'Series A'}}]);
  wrapper.unmount();
});

it('clears the copied source when switching workspaces and respects read-only state', async () => {
  const { mount } = await import('@vue/test-utils');
  const { default: RecordClipboard } = await import('../src/review/paper/RecordClipboard.vue');
  const wrapper = mount(RecordClipboard, { props: {kind: 'compound', workspaceId: ids.workspace, workspaceVersion: 1, source: {id: ids.compounds[0]!, label: 'C1'}, records: [], disabled: true} });
  expect(wrapper.get('[data-copy-record]').attributes('disabled')).toBeDefined();
  await wrapper.setProps({disabled: false});
  await wrapper.get('[data-copy-record]').trigger('click');
  expect(wrapper.get('[data-paste-record]').attributes('disabled')).toBeUndefined();
  await wrapper.setProps({workspaceId: '30000000-0000-4000-8000-000000000098'});
  expect(wrapper.get('[data-paste-record]').attributes('disabled')).toBeDefined();
  wrapper.unmount();
});

it('keeps the preview and reports version conflicts without claiming a new record', async () => {
  const { mount } = await import('@vue/test-utils');
  const { default: RecordClipboard } = await import('../src/review/paper/RecordClipboard.vue');
  vi.stubGlobal('fetch', vi.fn(async () => response({code: 'WORKSPACE_VERSION_CONFLICT', message: 'Workspace changed', details: {}, request_id: 'clipboard-test'}, 409)));
  const wrapper = mount(RecordClipboard, {props: {kind: 'compound', workspaceId: ids.workspace, workspaceVersion: 1, source: {id: ids.compounds[0]!, label: 'C1'}, records: []}});
  await wrapper.get('[data-copy-record]').trigger('click');
  await wrapper.get('[data-paste-record]').trigger('click');
  await wrapper.get('[data-paste-label]').setValue('New');
  await wrapper.get('[data-paste-preview]').trigger('submit');
  await flushPromises();
  expect(wrapper.emitted('conflict')).toHaveLength(1);
  expect(wrapper.emitted('pasted')).toBeUndefined();
  expect(wrapper.find('[data-paste-preview]').exists()).toBe(true);
  expect(wrapper.get('[role=alert]').text()).toContain('内容已更新');
  wrapper.unmount();
});

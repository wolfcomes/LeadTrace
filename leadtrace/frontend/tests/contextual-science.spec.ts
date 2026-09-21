import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import ActivityEditor from '../src/review/paper/ActivityEditor.vue';
import { activities, compounds, evidence, ids, installReviewer, lineages, links, mountWorkspace, response, workspace } from './paper-science-v2-fixtures';
import type { PaperWorkspace } from '../src/v2/types';

beforeEach(() => {
  installReviewer();
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const path = new URL(String(input), 'http://test').pathname;
    if (path.endsWith('/compounds')) return response({ workspace_id: ids.workspace, workspace_version: 1, items: compounds, total: compounds.length });
    if (path.endsWith('/structure')) return response({ compound_id: path.split('/')[4], workspace_version: 1, structure: null });
    if (path.endsWith('/evidence')) return response({ workspace_id: ids.workspace, workspace_version: 1, items: [evidence], total: 1 });
    if (path.endsWith('/lineages')) return response({ workspace_id: ids.workspace, workspace_version: 1, items: lineages, total: lineages.length });
    if (path.endsWith('/evidence-links')) { const edge_id = path.split('/')[4]; const items = links.filter(l => l.edge_id === edge_id); return response({ edge_id, workspace_version: 1, items, total: items.length }); }
    if (path.endsWith('/activities')) { const compound_id = path.split('/')[4]; const items = compound_id === ids.compounds[0] ? activities.map(a => ({ ...a, evidence_id: evidence.id })) : []; return response({ compound_id, workspace_version: 1, items, total: items.length }); }
    return response(workspace());
  }));
});
afterEach(() => vi.unstubAllGlobals());

it('scopes activity requests and evidence to the selected compound, then clears on switching', async () => {
  const wrapper = mount(ActivityEditor, { props: { workspace: workspace() as PaperWorkspace, compound: compounds[0] as any } });
  await flushPromises();
  expect(wrapper.find('[data-activity-filter]').exists()).toBe(false);
  expect(wrapper.findAll('[data-activity-row]')).toHaveLength(2);
  expect(wrapper.get('[data-activity-row]').text()).toContain(evidence.quoted_text);
  expect(vi.mocked(fetch).mock.calls.filter(c => String(c[0]).endsWith('/activities'))).toHaveLength(1);
  await wrapper.setProps({ compound: compounds[1] as any }); await flushPromises();
  expect(wrapper.findAll('[data-activity-row]')).toHaveLength(0);
  expect(wrapper.text()).toContain('当前化合物尚无活性记录');
  expect(wrapper.text()).not.toContain(evidence.quoted_text);
  wrapper.unmount();
});

it('places activity deep links in compounds and removes the old navigation tab', async () => {
  const { wrapper, router } = await mountWorkspace('evidence', activities[0]!.id);
  await flushPromises();
  expect(router.currentRoute.value.query.tab).toBe('compounds');
  expect(wrapper.get('[data-workspace-tabs]').text()).not.toContain('证据与活性');
  expect(wrapper.get('.compound-detail-panel').text()).toContain('活性数据');
  wrapper.unmount();
});

it('shows evidence under every linked edge with its role and allows edges with no evidence', async () => {
  const { wrapper } = await mountWorkspace('lineages');
  await flushPromises();
  const row = wrapper.get(`[data-edge-id="${ids.edges[0]}"]`);
  expect(row.text()).toContain(evidence.quoted_text);
  expect(row.text()).toContain('supports');
  expect(row.get('[data-evidence-pdf-locator]').attributes('href')).toContain('#page=2');
  wrapper.unmount();
});

it('retains an edge without evidence and exposes contextual link editing for a reviewer', async () => {
  const { wrapper } = await mountWorkspace('lineages');
  const unlinked = wrapper.findAll('[data-edge-id]').find(row => !row.find('[data-edge-evidence-link]').exists());
  expect(unlinked).toBeDefined();
  expect(unlinked!.text()).toContain('尚未关联证据');
  await unlinked!.get('[data-manage-edge-evidence]').trigger('click'); await flushPromises();
  expect(unlinked!.get('.evidence-editor').text()).not.toContain(evidence.quoted_text);
  await unlinked!.get('[data-toggle-evidence-library]').trigger('click');
  expect(unlinked!.get('.evidence-editor').text()).toContain(evidence.quoted_text);
  await unlinked!.get('[data-link-existing-evidence]').trigger('click');
  const choices = unlinked!.get('.existing-evidence-link-form').findAll('select')[0]!.findAll('option');
  expect(choices).toHaveLength(1);
  expect(choices[0]!.attributes('value')).toBe(unlinked!.attributes('data-edge-id'));
  wrapper.unmount();
});

it('ignores an old compound response when the selection changes before it finishes', async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  let finish!: (value: Response) => void;
  vi.mocked(fetch).mockImplementation((input, init) => {
    if (String(input).includes(ids.compounds[0]!) && String(input).endsWith('/activities')) return new Promise(resolve => { finish = resolve; });
    return original(input, init);
  });
  const wrapper = mount(ActivityEditor, { props: { workspace: workspace() as PaperWorkspace, compound: compounds[0] as any } });
  await flushPromises();
  await wrapper.setProps({ compound: compounds[1] as any }); await flushPromises();
  finish(response({ compound_id: ids.compounds[0], workspace_version: 1, items: activities, total: 2 })); await flushPromises();
  expect(wrapper.findAll('[data-activity-row]')).toHaveLength(0);
  expect(wrapper.text()).toContain('当前化合物尚无活性记录');
  wrapper.unmount();
});

it('does not call a failed activity load an absence of reported activity', async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation((input, init) => String(input).endsWith('/activities') ? Promise.resolve(response({ error: 'unavailable' }, 503)) : original(input, init));
  const wrapper = mount(ActivityEditor, { props: { workspace: workspace() as PaperWorkspace, compound: compounds[0] as any } }); await flushPromises();
  expect(wrapper.get('[role="alert"]').text()).toContain('暂时无法读取');
  expect(wrapper.text()).not.toContain('当前化合物尚无活性记录');
  wrapper.unmount();
});

it('shows image evidence on its original PDF page and preserves a read-only overlay', async () => {
  const { default: EvidenceExcerpt } = await import('../src/review/paper/EvidenceExcerpt.vue');
  const wrapper = mount(EvidenceExcerpt, {
    props: { workspace: workspace() as PaperWorkspace, evidence: { ...evidence, kind: 'image', bbox: { x0: .1, y0: .2, x1: .7, y1: .8 } } as any },
    global: { stubs: { PdfReviewCanvas: true } },
  });
  await wrapper.get('[data-show-evidence-region]').trigger('click');
  const viewer = wrapper.findComponent({ name: 'PdfReviewCanvas' });
  expect(viewer.props('page')).toBe(2);
  expect(viewer.props('regions')[0]).toMatchObject({ id: evidence.id, x0: .1, y1: .8 });
  expect(viewer.props('readOnly')).toBe(true);
  wrapper.unmount();
});

it('keeps contextual activity edits unavailable in read-only mode', async () => {
  const wrapper = mount(ActivityEditor, { props: { workspace: workspace() as PaperWorkspace, compound: compounds[0] as any, readOnly: true } });await flushPromises();
  expect(wrapper.get('[data-add-activity]').attributes('disabled')).toBeDefined();
  expect(wrapper.find('[data-edit-activity]').exists()).toBe(false);
  expect(wrapper.findAll('[data-evidence-excerpt]')).toHaveLength(2);
  wrapper.unmount();
});

it('propagates a contextual evidence version conflict without pretending to save a link', async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation((input, init) => init?.method === 'POST' ? Promise.resolve(response({ code: 'WORKSPACE_VERSION_CONFLICT', message: 'Stale version', request_id: 'context-test', details: {} }, 409)) : original(input, init));
  const { default: EvidenceEditor } = await import('../src/review/paper/EvidenceEditor.vue');
  const wrapper = mount(EvidenceEditor, { props: { workspace: workspace() as PaperWorkspace, edgeId: ids.edges[2] } });await flushPromises();
  await wrapper.get('[data-toggle-evidence-library]').trigger('click');
  await wrapper.get('[data-link-existing-evidence]').trigger('click');
  await wrapper.get('[data-save-existing-link]').trigger('click');await flushPromises();
  expect(wrapper.emitted('conflict')).toHaveLength(1);
  expect(wrapper.emitted('mutated')).toBeUndefined();
  wrapper.unmount();
});

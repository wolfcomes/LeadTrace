import { flushPromises } from '@vue/test-utils';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import LineageGraph from '../src/review/paper/LineageGraph.vue';
import { compounds, edges, evidence, ids, installReviewer, lineages, links, mountWorkspace, response, workspace } from './paper-science-v2-fixtures';
beforeEach(() => {
  installReviewer();
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const path = new URL(String(input), 'http://test').pathname;
    if (path.endsWith('/compounds')) return response({ workspace_id: ids.workspace, workspace_version: 1, items: compounds, total: compounds.length });
    if (path.endsWith('/lineages')) return response({ workspace_id: ids.workspace, workspace_version: 1, items: lineages, total: lineages.length });
    if (path.endsWith('/evidence')) return response({ workspace_id: ids.workspace, workspace_version: 1, items: [evidence], total: 1 });
    if (path.endsWith('/evidence-links')) { const edge_id = path.split('/')[4]; const items = links.filter(l => l.edge_id === edge_id); return response({ edge_id, workspace_version: 1, items, total: items.length }); }
    if (path.endsWith('/structure')) { const compound_id = path.split('/')[4]; return response({ workspace_version: 1, structure: compound_id === ids.compounds[1] ? null : {
      id: '30000000-0000-4000-8000-000000000091', paper_id: ids.paper, workspace_id: ids.workspace, compound_id,
      smiles: 'CC', canonical_smiles: 'CC', molfile: null, inchi: null, inchikey: null,
      depiction_asset_id: '30000000-0000-4000-8000-000000000092', status: 'draft', input_method: 'ai_prefill',
    } }); }
    return response(workspace());
  }));
});
afterEach(() => vi.unstubAllGlobals());
it('opens graph-selected Edge with correct endpoints and Evidence, and returns', async () => {
  const { wrapper, router } = await mountWorkspace('lineages');
  wrapper.findComponent(LineageGraph).vm.$emit('select-edge', edges[0]!.id);await flushPromises();
  expect(router.currentRoute.value.query.entity).toBe(edges[0]!.id);
  const detail = wrapper.get('[data-edge-detail]');
  expect(detail.findAll('[data-edge-endpoint]').map(c => c.attributes('data-compound-id'))).toEqual([edges[0]!.parent_compound_id, edges[0]!.child_compound_id]);
  expect(detail.text()).toContain(evidence.quoted_text);
  expect(detail.findAll('[data-endpoint-depiction]')).toHaveLength(2);
  expect(detail.get('[data-endpoint-compound-link]').attributes('href')).toContain(`tab=compounds&entity=${edges[0]!.parent_compound_id}`);
  expect(wrapper.get('[data-lineage-graph]').isVisible()).toBe(false);
  await detail.get('[data-return-lineage]').trigger('click');await flushPromises();
  expect(wrapper.find('[data-edge-detail]').exists()).toBe(false);
  expect(wrapper.findComponent(LineageGraph).attributes('style') || '').not.toContain('display: none');
  expect(router.currentRoute.value.query.entity).toBe(ids.lineages[0]);
  wrapper.unmount();
});
it('opens a deep-linked Edge with an honest missing-structure fallback', async () => {
  const { wrapper } = await mountWorkspace('lineages', edges[2]!.id);
  const cards = wrapper.get('[data-edge-detail]').findAll('[data-edge-endpoint]');
  expect(cards[0]!.attributes('data-compound-id')).toBe(ids.compounds[1]);
  expect(cards[0]!.text()).toContain('尚无结构');
  expect(cards[0]!.find('[data-endpoint-depiction]').exists()).toBe(false);
  expect(cards[1]!.find('[data-endpoint-depiction]').exists()).toBe(true);
  wrapper.unmount();
});
it('supports accessible Edge buttons and browser back/forward', async () => {
  const { wrapper, router } = await mountWorkspace('lineages', ids.lineages[0]);
  await wrapper.get(`[data-edge-id="${edges[0]!.id}"] [data-open-edge]`).trigger('click');await flushPromises();
  expect(wrapper.get('[data-edge-detail]').attributes('data-selected-edge-id')).toBe(edges[0]!.id);
  router.back();await new Promise(resolve => setTimeout(resolve, 0));await flushPromises();
  expect(wrapper.find('[data-edge-detail]').exists()).toBe(false);
  router.forward();await new Promise(resolve => setTimeout(resolve, 0));await flushPromises();
  expect(wrapper.get('[data-edge-detail]').attributes('data-selected-edge-id')).toBe(edges[0]!.id);
  wrapper.unmount();
});
it('keeps endpoint details usable when a depiction image fails', async () => {
  const { wrapper } = await mountWorkspace('lineages', edges[0]!.id);
  await wrapper.get('[data-endpoint-depiction]').trigger('error');
  expect(wrapper.get('[data-edge-endpoint]').text()).toContain('结构图片暂不可用');
  expect(wrapper.get('[data-edge-endpoint]').find('[data-endpoint-compound-link]').exists()).toBe(true);
  expect(wrapper.get('[data-edge-detail]').text()).toContain(evidence.quoted_text);
  wrapper.unmount();
});
it('retains read-only controls and relationship navigation for admin readers', async () => {
  const { useAuthStore } = await import('../src/auth/store');
  useAuthStore().acceptSession({ user: { username: 'admin', display_name: 'Admin', role: 'admin', must_change_password: false }, csrf_token: 'admin-csrf' });
  const { wrapper } = await mountWorkspace('lineages', edges[0]!.id);
  expect(wrapper.get('[data-edge-detail] [data-edit-edge]').attributes('disabled')).toBeDefined();
  expect(wrapper.get('[data-edge-detail] [data-delete-edge]').attributes('disabled')).toBeDefined();
  expect(wrapper.find('[data-manage-edge-evidence]').exists()).toBe(false);
  await wrapper.get('[data-return-lineage]').trigger('click');await flushPromises();
  expect(wrapper.find('[data-edge-detail]').exists()).toBe(false);
  wrapper.unmount();
});
it('defaults to points and retains structure mode across Edge detail navigation', async () => {
  const { wrapper } = await mountWorkspace('lineages');
  expect(wrapper.get('[data-graph-mode="points"]').attributes('aria-pressed')).toBe('true');
  expect(wrapper.find('[data-structure-count]').exists()).toBe(false);
  await wrapper.get('[data-graph-mode="structures"]').trigger('click');
  expect(wrapper.get('[data-graph-mode="structures"]').attributes('aria-pressed')).toBe('true');
  expect(wrapper.find('[data-structure-count]').exists()).toBe(true);
  wrapper.findComponent(LineageGraph).vm.$emit('select-edge', edges[0]!.id);await flushPromises();
  await wrapper.get('[data-return-lineage]').trigger('click');await flushPromises();
  expect(wrapper.get('[data-graph-mode="structures"]').attributes('aria-pressed')).toBe('true');
  await wrapper.get('[data-graph-mode="points"]').trigger('click');
  expect(wrapper.get('[data-graph-mode="points"]').attributes('aria-pressed')).toBe('true');
  expect(wrapper.find('[data-structure-count]').exists()).toBe(false);
  wrapper.unmount();
});

it('refreshes an endpoint depiction and clears its old image failure after a structure change', async () => {
  const { mount } = await import('@vue/test-utils');
  const { default: EdgeCompoundCard } = await import('../src/review/paper/EdgeCompoundCard.vue');
  const structure={id:'30000000-0000-4000-8000-000000000091',paper_id:ids.paper,workspace_id:ids.workspace,compound_id:ids.compounds[0]!,smiles:'CC',canonical_smiles:'CC',molfile:null,inchi:null,inchikey:null,depiction_asset_id:'30000000-0000-4000-8000-000000000092',status:'draft' as const,input_method:'manual_smiles' as const};
  const wrapper=mount(EdgeCompoundCard,{props:{compoundId:ids.compounds[0]!,workspaceId:ids.workspace,paperId:ids.paper,caption:'Parent',state:{status:'ready',structure}},global:{stubs:{RouterLink:true}}});
  const before=wrapper.get('[data-endpoint-depiction]').attributes('src');
  await wrapper.get('[data-endpoint-depiction]').trigger('error');
  expect(wrapper.find('[data-endpoint-depiction]').exists()).toBe(false);
  await wrapper.setProps({state:{status:'ready',structure:{...structure,smiles:'CCN',canonical_smiles:'CCN',depiction_asset_id:'30000000-0000-4000-8000-000000000093'}}});
  expect(wrapper.get('[data-endpoint-depiction]').attributes('src')).not.toBe(before);
  wrapper.unmount();
});

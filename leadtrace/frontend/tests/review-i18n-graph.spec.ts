import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { nextTick } from 'vue';
import { afterEach, expect, it, vi } from 'vitest';
import type { Compound, Lineage } from '../src/v2/types';
import { setLocale } from '../src/i18n';
vi.mock('../src/v2/workbench',async (original)=>({...await original<typeof import('../src/v2/workbench')>(),getGraphLayout:vi.fn(async (_id,mode)=>({revision:0,mode,positions:{},edge_controls:{}}))}));
const state = vi.hoisted(() => ({ graphs: [] as any[] }));
vi.mock('cytoscape', () => ({ default: vi.fn((options: any) => {
  const nodes = new Map(options.elements.filter((e: any) => !e.data.source).map((e: any) => [e.data.id, {
    value: { ...e.data },
    id() { return this.value.id; },
    position() { return {x:0,y:0}; },
    data(name: any, value: any) { if (typeof name === 'object') Object.assign(this.value, name); else this.value[name] = value; },
    removeData(name: string) { delete this.value[name]; },
  }]));
  const collection = Object.assign([...nodes.values()], { filter: () => Object.assign([...nodes.values()], {first: () => ({length:0})}) });
  const graph = { nodes: () => collection, edges: () => [],
    batch: (fn: () => void) => fn(), getElementById: (id: string) => nodes.get(id),
    resize: vi.fn(), fit: vi.fn(), zoom: vi.fn(() => 1), pan: vi.fn(() => ({ x: 40, y: 60 })),
    center: vi.fn(), on: vi.fn(), destroy: vi.fn(), layout: vi.fn(() => ({ run: vi.fn() })),
    values: nodes,
  };
  state.graphs.push(graph); return graph;
}) }));
import LineageGraph from '../src/review/paper/LineageGraph.vue';
afterEach(() => { setLocale('zh-CN'); vi.restoreAllMocks(); state.graphs.length = 0; });
it('updates canvas fallback labels without recreating the graph, layout or viewport', async () => {
  setActivePinia(createPinia());
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(800);
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(500);
  const lineage = { id: 'l', lineage_type: 'sar', members: [{ compound_id: 'a', role: 'root' }, { compound_id: 'b', role: 'unspecified' }], edges: [{ id: 'e', parent_compound_id: 'a', child_compound_id: 'b', relation_type: 'comparison' }] } as Lineage;
  const compounds = [{ id: 'a', compound_label: '24' }, { id: 'b', compound_label: '55' }] as Compound[];
  const wrapper = mount(LineageGraph, { props: { lineage, compounds, structures: { a: { status: 'ready', structure: null }, b: { status: 'ready', structure: null } } } });
  await flushPromises();
  await wrapper.get('[data-graph-mode="structures"]').trigger('click'); await flushPromises();
  const count = state.graphs.length;
  const graph = state.graphs[count - 1];
  expect(graph.values.get('a').value.label).toBe('24\n暂无结构图');
  const layoutCalls = graph.layout.mock.calls.length;
  const zoomCalls = graph.zoom.mock.calls.length;
  const panCalls = graph.pan.mock.calls.length;
  setLocale('en'); await nextTick(); await flushPromises();
  expect(graph.values.get('a').value.label).toBe('24\nNo structure image');
  expect(state.graphs.length).toBe(count);
  expect(graph.destroy).not.toHaveBeenCalled();
  expect(graph.layout).toHaveBeenCalledTimes(layoutCalls);
  expect(graph.zoom).toHaveBeenCalledTimes(zoomCalls);
  expect(graph.pan).toHaveBeenCalledTimes(panCalls);
  expect(wrapper.get('[data-graph-mode="structures"]').attributes('aria-pressed')).toBe('true');
  wrapper.unmount();
});

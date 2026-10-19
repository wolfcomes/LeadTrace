import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import ActivityComparison from '../src/review/paper/ActivityComparison.vue';
import { activities, compounds, ids, installReviewer, response, workspace } from './paper-science-v2-fixtures';

beforeEach(installReviewer);
afterEach(() => vi.unstubAllGlobals());
const row = { ...activities[0], value: '0.123456789012345678901', review_hint: 'Check source', context: 'Human enzyme' };
function data(version = 1) {
  return { workspace_id: ids.workspace, workspace_version: version, compounds, activities: [
    row,
    { ...row, id: ids.activities[1], operator: '<', value: '2' },
    { ...row, id: '30000000-0000-4000-8000-000000000073', unit: 'μM', value: '3' },
    { ...row, id: '30000000-0000-4000-8000-000000000074', context: 'Mouse enzyme', value: '4' },
    { ...row, id: '30000000-0000-4000-8000-000000000075', metric: 'Ki', value: '5' },
  ] };
}
function install(payload = data()) {
  const fetcher = vi.fn(async (_input: RequestInfo | URL) => response(payload)); vi.stubGlobal('fetch', fetcher); return fetcher;
}
const props = () => ({ workspace: workspace() as any, active: true });

it('separates measurement conditions and units, preserving duplicates, precision and missing rows', async () => {
  const fetcher = install();
  const w = mount(ActivityComparison, {props: props()}); await flushPromises();
  expect(w.findAll('[data-comparison-column]')).toHaveLength(4);
  expect(w.findAll('[data-comparison-row]')).toHaveLength(4);
  expect(w.findAll('[data-comparison-activity]')).toHaveLength(5);
  expect(w.text()).toContain('0.123456789012345678901');
  expect(w.text()).toContain('< 2');
  expect(w.findAll('[data-comparison-row]')[1]!.text()).toContain('—');
  await w.findAll('[data-review-hint] button')[0]!.trigger('click');
  expect(w.text()).toContain('Check source');
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(String(fetcher.mock.calls[0]?.[0])).toContain('/activity-comparison');
  expect(w.find('input[type=number]').exists()).toBe(false);
  w.unmount();
});

it('searches compounds, filters columns and emits exact record identities', async () => {
  install(); const w = mount(ActivityComparison,{props:props()}); await flushPromises();
  await w.get('[data-comparison-search]').setValue('compound 1');
  expect(w.findAll('[data-comparison-row]')).toHaveLength(1);
  await w.get('[data-comparison-clear-columns]').trigger('click');
  await w.findAll('[data-comparison-column-choice]')[0]!.setValue(true);
  expect(w.findAll('[data-comparison-column]')).toHaveLength(1);
  await w.findAll('[data-comparison-activity]')[1]!.trigger('click');
  expect(w.emitted('open')?.[0]).toEqual([ids.compounds[0], ids.activities[1]]);
  await w.get('[data-comparison-compound]').trigger('click');
  expect(w.emitted('open')?.[1]).toEqual([ids.compounds[0]]);
  w.unmount();
});

it('retains filters and scroll while returning and refreshes saved values', async () => {
  const fetcher = install(); const w = mount(ActivityComparison,{props:props()}); await flushPromises();
  await w.get('[data-comparison-search]').setValue('C1');
  await w.get('[data-comparison-sort]').setValue('label');
  const viewport = w.get('[data-comparison-scroll]').element;
  viewport.scrollTop = 120; viewport.scrollLeft = 80;
  await w.get('[data-comparison-scroll]').trigger('scroll');
  await w.setProps({active:false});
  fetcher.mockImplementation(async () => response({...data(2), activities:[{...row,value:'9'}]}));
  await w.setProps({workspace:workspace(2) as any});
  await w.setProps({active:true}); await flushPromises();
  expect(w.get('[data-comparison-search]').element).toHaveProperty('value','C1');
  expect(w.get('[data-comparison-sort]').element).toHaveProperty('value','label');
  expect(w.text()).toContain('= 9');
  expect(w.get('[data-comparison-scroll]').element.scrollLeft).toBe(80);
  expect(w.get('[data-comparison-scroll]').element.scrollTop).toBe(120);
  w.unmount();
});

it('shows load failure and retries without presenting missing measurements', async () => {
  const fetcher = install(); fetcher.mockRejectedValueOnce(new Error('offline'));
  const w = mount(ActivityComparison,{props:props()}); await flushPromises();
  expect(w.get('[role=alert]').text()).toContain('活性对比暂时无法读取');
  expect(w.find('[data-comparison-row]').exists()).toBe(false);
  await w.get('[data-comparison-retry]').trigger('click');await flushPromises();
  expect(w.findAll('[data-comparison-row]')).toHaveLength(4);
  w.unmount();
});

it('blocks detail navigation while another editor has pending changes', async () => {
  install();const w = mount(ActivityComparison,{props:{...props(),blocked:true}});await flushPromises();
  expect(w.findAll('[data-comparison-activity]')[0]!.attributes('disabled')).toBeDefined();
  await w.findAll('[data-comparison-activity]')[0]!.trigger('click');
  expect(w.emitted('open')).toBeUndefined(); w.unmount();
});


it('ignores an obsolete response after switching workspaces and resets filters', async () => {
  let finish!: (response: Response) => void;
  const fetcher = install(); fetcher.mockImplementationOnce(() => new Promise(resolve => {finish = resolve;}));
  const w = mount(ActivityComparison,{props:props()});
  await w.get('[data-comparison-search]').setValue('old');
  const newId = '30000000-0000-4000-8000-000000000090';
  fetcher.mockImplementation(async () => response({...data(),workspace_id:newId,compounds:[],activities:[]}));
  await w.setProps({workspace:{...workspace(),id:newId} as any});await flushPromises();
  finish(response(data()));await flushPromises();
  expect(w.get('[data-comparison-search]').element).toHaveProperty('value','');
  expect(w.findAll('[data-comparison-row]')).toHaveLength(0);
  expect(w.text()).toContain('当前文章尚无 Compound');w.unmount();
});

it('naturally sorts compound identifiers without sorting or averaging measurements', async () => {
  install({...data(),compounds:[{...compounds[0]!,compound_label:'C10'},{...compounds[1]!,compound_label:'C2'}]});
  const w = mount(ActivityComparison,{props:props()});await flushPromises();
  await w.get('[data-comparison-sort]').setValue('label');
  expect(w.findAll('[data-comparison-compound]').map(x=>x.text())).toEqual(['C2','C10']);
  expect(w.findAll('[data-comparison-activity]')).toHaveLength(5);w.unmount();
});

it('does not advance editor versions just by reading a newer comparison', async () => {
  install(data(2));
  const w = mount(ActivityComparison,{props:{...props(),blocked:true}});await flushPromises();
  expect(w.emitted('version')).toBeUndefined();
  await w.setProps({blocked:false});await flushPromises();
  expect(w.emitted('version')).toBeUndefined();
  w.unmount();
});

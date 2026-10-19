import {tableStorageKey} from '../src/review/paper/activityTableBuilder';
import { flushPromises } from '@vue/test-utils';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { activities, compounds, ids, installReviewer, mountWorkspace, response, workspace, addComparisonColumn } from './paper-science-v2-fixtures';

beforeEach(()=>{installReviewer();localStorage.clear();localStorage.setItem(tableStorageKey('reviewer',ids.workspace),JSON.stringify({version:1,tables:[],activeId:null}));});
afterEach(() => vi.unstubAllGlobals());

it('opens the exact Activity without scanning other compounds and retains comparison state on return', async () => {
  let version = 1;
  const records = activities.map(a => ({...a}));
  const writes: string[] = [], activityReads: string[] = [];
  vi.stubGlobal('fetch',vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (init?.method && init.method !== 'GET') writes.push(path);
    if (path.endsWith('/activity-comparison')) return response({workspace_id:ids.workspace,workspace_version:version,compounds,activities:records});
    if (path.endsWith('/edit-history')) return response({workspace_version:version,undo_action:null,redo_action:null});
    if (path.endsWith('/review-progress')) return response({workspace_id:ids.workspace,workspace_version:version,tracking_started:false,items:[],sections:[]});
    if (path.endsWith('/compound-highlights') || path.endsWith('/evidence')) return response({workspace_id:ids.workspace,workspace_version:version,items:[],total:0});
    if (path.endsWith('/compounds')) return response({workspace_id:ids.workspace,workspace_version:version,items:compounds,total:compounds.length});
    if (path.endsWith('/structure')) return response({compound_id:ids.compounds[0],workspace_version:version,structure:null});
    if (path.endsWith('/source-images')) return response({compound_id:ids.compounds[0],workspace_version:version,items:[],total:0});
    if (path.endsWith('/activities')) {activityReads.push(path);return response({compound_id:ids.compounds[0],workspace_version:version,items:records,total:records.length});}
    if (path === '/api/v2/workspaces/'+ids.workspace) return response(workspace(version));
    return response({},404);
  }));
  const {wrapper,router} = await mountWorkspace('activity-comparison');
  expect(wrapper.get('[data-workspace-tab-key="activity-comparison"]').attributes('aria-current')).toBe('page');
  await wrapper.get('[data-comparison-search]').setValue('Compound 1');
  await wrapper.get('[data-comparison-sort]').setValue('label');
  expect(writes).toEqual([]);
  const target=activities[1]!;
  await addComparisonColumn(wrapper,target);
  await wrapper.get(`[data-comparison-activity][data-activity-id="${ids.activities[1]}"]`).trigger('click');await flushPromises();
  expect(router.currentRoute.value.query).toMatchObject({tab:'compounds',entity:ids.activities[1]});
  expect(wrapper.get(`[data-activity-row][data-activity-id="${ids.activities[1]}"]`).classes()).toContain('selected');
  expect(activityReads.length).toBeGreaterThan(0);
  expect(activityReads.every(path => path.includes(ids.compounds[0]!))).toBe(true);
  records[1]!.value='99';version=2;
  await wrapper.get('[data-return-comparison]').trigger('click');await flushPromises();
  expect(router.currentRoute.value.query.tab).toBe('activity-comparison');
  expect(wrapper.get('[data-comparison-search]').element).toHaveProperty('value','Compound 1');
  expect(wrapper.get('[data-comparison-sort]').element).toHaveProperty('value','label');
  expect(wrapper.get(`[data-comparison-activity][data-activity-id="${ids.activities[1]}"]`).text()).toContain('99');
  expect(writes).toEqual([]);
  wrapper.unmount();
});

it('reveals the same Activity again when returning from the comparison tab', async () => {
  const {mount} = await import('@vue/test-utils');
  const {default: ActivityEditor} = await import('../src/review/paper/ActivityEditor.vue');
  const scroll = vi.fn();
  const previous = HTMLElement.prototype.scrollIntoView;
  HTMLElement.prototype.scrollIntoView = scroll;
  vi.stubGlobal('fetch',vi.fn(async (input: RequestInfo | URL) => String(input).endsWith('/evidence')
    ? response({workspace_id:ids.workspace,workspace_version:1,items:[],total:0})
    : response({compound_id:ids.compounds[0],workspace_version:1,items:activities,total:activities.length})));
  const w = mount(ActivityEditor,{props:{workspace:workspace() as any,compound:compounds[0] as any,selectedEntityId:ids.activities[1],active:true}});
  try {
    await flushPromises();
    await w.setProps({active:false});scroll.mockClear();
    await w.setProps({active:true});await flushPromises();
    expect(scroll).toHaveBeenCalledWith({block:'center'});
  } finally {w.unmount();HTMLElement.prototype.scrollIntoView = previous;}
});

it('locks editing until the workspace refresh for opening a comparison record completes', async () => {
  let reads = 0;
  let finish!: (value: Response) => void;
  vi.stubGlobal('fetch',vi.fn(async (input: RequestInfo | URL) => {
    const path=String(input);
    if(path === '/api/v2/workspaces/'+ids.workspace) {
      if(++reads === 1)return response(workspace());
      return new Promise<Response>(resolve=>{finish=resolve;});
    }
    if(path.endsWith('/activity-comparison'))return response({workspace_id:ids.workspace,workspace_version:1,compounds,activities});
    if(path.endsWith('/compounds'))return response({workspace_id:ids.workspace,workspace_version:1,items:compounds,total:compounds.length});
    if(path.endsWith('/structure'))return response({workspace_version:1,structure:null});
    if(path.endsWith('/activities'))return response({compound_id:ids.compounds[0],workspace_version:1,items:activities,total:activities.length});
    if(path.endsWith('/source-images'))return response({compound_id:ids.compounds[0],workspace_version:1,items:[],total:0});
    if(path.endsWith('/evidence')||path.endsWith('/compound-highlights'))return response({workspace_id:ids.workspace,workspace_version:1,items:[],total:0});
    if(path.endsWith('/edit-history'))return response({workspace_version:1,undo_action:null,redo_action:null});
    if(path.endsWith('/review-progress'))return response({workspace_id:ids.workspace,workspace_version:1,tracking_started:false,items:[],sections:[]});
    return response({},404);
  }));
  const {wrapper,router}=await mountWorkspace('activity-comparison');
  await addComparisonColumn(wrapper,activities[0]!);
  await wrapper.findAll('[data-comparison-activity]')[0]!.trigger('click');await flushPromises();
  expect(reads).toBe(2);
  expect(router.currentRoute.value.query.tab).toBe('activity-comparison');
  expect(wrapper.findAll('[data-comparison-activity]')[0]!.attributes('disabled')).toBeDefined();
  // Even a manual tab switch while GET is pending cannot start another edit.
  await wrapper.get('[data-workspace-tab-key="compounds"]').trigger('click');await flushPromises();
  expect(wrapper.find('[data-edit-compound]').exists()).toBe(false);
  finish(response(workspace(2)));await flushPromises();
  expect(wrapper.find('[data-edit-compound]').exists()).toBe(true);
  wrapper.unmount();
});


it('hides previously loaded Compound controls until fresh records arrive after comparison navigation', async () => {
  let version=1;
  const pending: Array<(value: Response)=>void>=[];
  vi.stubGlobal('fetch',vi.fn(async (input: RequestInfo | URL) => {
    const path=String(input);
    if(path === '/api/v2/workspaces/'+ids.workspace)return response(workspace(version));
    if(path.endsWith('/activity-comparison'))return response({workspace_id:ids.workspace,workspace_version:version,compounds,activities});
    if(path.endsWith('/compounds')) {
      if(version===2)return new Promise<Response>(resolve=>pending.push(resolve));
      return response({workspace_id:ids.workspace,workspace_version:version,items:compounds,total:compounds.length});
    }
    if(path.endsWith('/structure'))return response({workspace_version:version,structure:null});
    if(path.endsWith('/activities'))return response({compound_id:ids.compounds[0],workspace_version:version,items:activities,total:activities.length});
    if(path.endsWith('/source-images'))return response({compound_id:ids.compounds[0],workspace_version:version,items:[],total:0});
    if(path.endsWith('/evidence')||path.endsWith('/compound-highlights'))return response({workspace_id:ids.workspace,workspace_version:version,items:[],total:0});
    if(path.endsWith('/edit-history'))return response({workspace_version:version,undo_action:null,redo_action:null});
    if(path.endsWith('/review-progress'))return response({workspace_id:ids.workspace,workspace_version:version,tracking_started:false,items:[],sections:[]});
    return response({},404);
  }));
  const {wrapper}=await mountWorkspace('compounds');
  expect(wrapper.find('[data-edit-compound]').exists()).toBe(true);
  await wrapper.get('[data-workspace-tab-key="activity-comparison"]').trigger('click');await flushPromises();
  await addComparisonColumn(wrapper,activities[0]!);
  version=2;
  await wrapper.findAll('[data-comparison-activity]')[0]!.trigger('click');await flushPromises();
  expect(pending.length).toBeGreaterThan(0);
  expect(wrapper.find('[data-edit-compound]').exists()).toBe(false);
  for(const resolve of pending)resolve(response({workspace_id:ids.workspace,workspace_version:2,items:compounds,total:compounds.length}));
  await flushPromises();
  expect(wrapper.find('[data-edit-compound]').exists()).toBe(true);
  wrapper.unmount();
});

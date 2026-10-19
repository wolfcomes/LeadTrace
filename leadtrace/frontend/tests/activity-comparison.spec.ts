import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import ActivityComparison from '../src/review/paper/ActivityComparison.vue';
import { activities, compounds, ids, installReviewer, response, workspace, addComparisonColumn } from './paper-science-v2-fixtures';
import { tableStorageKey } from '../src/review/paper/activityTableBuilder';
const first={...activities[0]!,value:'0.123456789012345678901',context:'100 nM, 24 h',review_hint:'Verify'};
const second={...first,id:ids.activities[1]!,compound_id:ids.compounds[1]!,context:'1000 nM, 24 h',value:'2'};
const third={...first,id:'30000000-0000-4000-8000-000000000093',assay_name:'Assay B',unit:'μM',value:'3'};
const payload=(version=1)=>({workspace_id:ids.workspace,workspace_version:version,compounds,activities:[first,second,third]});
function install(data=payload()) {const fetcher=vi.fn(async()=>response(data));vi.stubGlobal('fetch',fetcher);return fetcher;}
const props=()=>({workspace:workspace() as any,active:true});
beforeEach(()=>{installReviewer();localStorage.clear();localStorage.setItem(tableStorageKey('reviewer',ids.workspace),JSON.stringify({version:1,tables:[],activeId:null}));});
afterEach(()=>vi.unstubAllGlobals());

it('starts with an explicit column choice and renames without changing measurement identity',async()=>{
 const fetcher=install();const w=mount(ActivityComparison,{props:props()});await flushPromises();
 expect(w.findAll('[data-comparison-row]')).toHaveLength(0);
 await addComparisonColumn(w,first,'My activity');
 expect(w.findAll('[data-comparison-column]')).toHaveLength(1);
 expect(w.findAll('[data-comparison-compound]').map(x=>x.text())).toEqual(['C1','C2']);
 expect(w.get('[data-comparison-column]').text()).toContain('My activity');
 expect(w.findAll('[data-comparison-activity]').map(x=>x.text())).toEqual(['= 0.123456789012345678901','= 2']);
 expect(w.emitted('version')).toBeUndefined();expect(fetcher).toHaveBeenCalledTimes(1);
 w.unmount();
});
it('previews literal condition matches and uses only explicitly selected Activity IDs',async()=>{
 install();const w=mount(ActivityComparison,{props:props()});await flushPromises();
 await w.get('[data-add-column]').trigger('click');
 await w.get('[data-column-measurement]').setValue(JSON.stringify([first.assay_name,first.metric,first.unit]));
 await w.get('[data-column-scope]').setValue('selected');
 await w.get('[data-column-record-search]').setValue('100 nM');
 expect(w.findAll('[data-column-record]')).toHaveLength(1);
 await w.get('[data-column-select-filtered]').trigger('click');
 await w.get('[data-column-label]').setValue('100 nM');
 await w.get('[data-column-apply]').trigger('click');await flushPromises();
 expect(w.findAll('[data-comparison-row]')).toHaveLength(1);
 expect(w.get('[data-comparison-activity]').attributes('data-activity-id')).toBe(first.id);
 await w.get('[data-comparison-activity]').trigger('click');
 expect(w.emitted('open')?.[0]).toEqual([first.compound_id,first.id]);
 w.unmount();
});
it('reorders/removes columns and switches between any and all matching rows',async()=>{
 install();const w=mount(ActivityComparison,{props:props()});await flushPromises();
 await addComparisonColumn(w,first,'A');await addComparisonColumn(w,third,'B');
 expect(w.findAll('[data-comparison-row]')).toHaveLength(2);
 await w.get('[data-comparison-row-mode]').setValue('all');
 expect(w.findAll('[data-comparison-row]')).toHaveLength(1);
 await w.findAll('[data-column-move-left]')[1]!.trigger('click');
 expect(w.findAll('[data-comparison-column]').map(x=>x.text())).toEqual(expect.arrayContaining([expect.stringContaining('B'),expect.stringContaining('A')]));
 expect(w.findAll('[data-comparison-column]')[0]!.text()).toContain('B');
 await w.findAll('[data-column-remove]')[0]!.trigger('click');
 expect(w.findAll('[data-comparison-row]')).toHaveLength(2);
 w.unmount();
});
it('saves named configs without values and reloads them against current server records',async()=>{
 const fetcher=install();let w=mount(ActivityComparison,{props:props()});await flushPromises();
 await addComparisonColumn(w,first,'Primary');await w.get('[data-table-name]').setValue('Potency');
 await w.get('[data-save-table]').trigger('click');
 const key=tableStorageKey('reviewer',ids.workspace),saved=localStorage.getItem(key);
 expect(saved).toContain('Potency');expect(saved).not.toContain(first.value);
 w.unmount();fetcher.mockImplementation(async()=>response({...payload(2),activities:[{...first,value:'99'},second,third]}));
 w=mount(ActivityComparison,{props:props()});await flushPromises();
 expect(w.get('[data-table-name]').element).toHaveProperty('value','Potency');
 expect(w.findAll('[data-comparison-activity]')[0]!.text()).toBe('= 99');
 expect(w.emitted('version')).toBeUndefined();w.unmount();
});
it('keeps independent saved tables and requires explicit discard before switching dirty settings',async()=>{
 install();const w=mount(ActivityComparison,{props:props()});await flushPromises();
 await addComparisonColumn(w,first,'A');await w.get('[data-table-name]').setValue('One');await w.get('[data-save-table]').trigger('click');
 const one=(w.get('[data-saved-table]').element as HTMLSelectElement).value;
 await w.get('[data-new-table]').trigger('click');await addComparisonColumn(w,third,'B');await w.get('[data-table-name]').setValue('Two');await w.get('[data-save-table]').trigger('click');
 await w.get('[data-table-name]').setValue('Unsaved');await w.get('[data-saved-table]').setValue(one);
 expect(w.get('[data-table-name]').element).toHaveProperty('value','Unsaved');
 await w.get('[data-discard-table-changes]').trigger('click');
 expect(w.get('[data-table-name]').element).toHaveProperty('value','One');
 expect(w.get('[data-comparison-column]').text()).toContain('A');w.unmount();
});
it('preserves selection, filters and scroll on return and refreshes saved values',async()=>{
 const fetcher=install();const w=mount(ActivityComparison,{props:props()});await flushPromises();await addComparisonColumn(w,first,'Primary');
 await w.get('[data-comparison-search]').setValue('C1');const el=w.get('[data-comparison-scroll]').element;el.scrollTop=120;el.scrollLeft=80;await w.get('[data-comparison-scroll]').trigger('scroll');
 await w.setProps({active:false});fetcher.mockImplementation(async()=>response({...payload(2),activities:[{...first,value:'99'},second]}));
 await w.setProps({active:true,workspace:workspace(2) as any});await flushPromises();
 expect(w.get('[data-comparison-search]').element).toHaveProperty('value','C1');expect(w.get('[data-comparison-column]').text()).toContain('Primary');
 expect(w.get('[data-comparison-activity]').text()).toBe('= 99');expect(w.get('[data-comparison-scroll]').element.scrollLeft).toBe(80);
 w.unmount();
});
it('rejects stale workspace responses and does not transfer table configurations',async()=>{
 let finish!:(r:Response)=>void;const fetcher=install();fetcher.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
 const w=mount(ActivityComparison,{props:props()});await w.get('[data-comparison-search]').setValue('old');
 const newid='30000000-0000-4000-8000-000000000090';fetcher.mockImplementation(async()=>response({...payload(),workspace_id:newid,compounds:[],activities:[]}));
 await w.setProps({workspace:{...workspace(),id:newid} as any});await flushPromises();finish(response(payload()));await flushPromises();
 expect(w.findAll('[data-comparison-row]')).toHaveLength(0);expect(w.get('[data-comparison-search]').element).toHaveProperty('value','');w.unmount();
});
it('shows API errors with retry and blocks detail opening for pending scientific edits',async()=>{
 const fetcher=install();fetcher.mockRejectedValueOnce(Error('offline'));const w=mount(ActivityComparison,{props:{...props(),blocked:true}});await flushPromises();
 expect(w.get('[role=alert]').text()).toContain('活性对比暂时无法读取');await w.get('[data-comparison-retry]').trigger('click');await flushPromises();
 await addComparisonColumn(w,first,'A');expect(w.get('[data-comparison-activity]').attributes('disabled')).toBeDefined();
 expect(w.emitted('open')).toBeUndefined();w.unmount();
});
it('reports local persistence failures without claiming a saved table or losing current columns',async()=>{
 install();const w=mount(ActivityComparison,{props:props()});await flushPromises();await addComparisonColumn(w,first,'A');await w.get('[data-table-name]').setValue('One');
 const spy=vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw Error('quota');});
 await w.get('[data-save-table]').trigger('click');expect(w.get('[data-table-storage-error]').text()).toContain('未能保存');
 expect(w.findAll('[data-comparison-column]')).toHaveLength(1);spy.mockRestore();w.unmount();
});
it('merges other tabs tables and rejects changes to the same saved table',async()=>{
 const lock=vi.fn(async (_key:string,run:()=>void)=>run());vi.stubGlobal('navigator',{locks:{request:lock}});
 install();const a=mount(ActivityComparison,{props:props()}),b=mount(ActivityComparison,{props:props()});await flushPromises();
 await a.get('[data-table-name]').setValue('One');await a.get('[data-save-table]').trigger('click');await flushPromises();
 await b.get('[data-table-name]').setValue('Two');await b.get('[data-save-table]').trigger('click');await flushPromises();
 const key=tableStorageKey('reviewer',ids.workspace);
 let stored=JSON.parse(localStorage.getItem(key)!);
 expect(stored.tables.map((t:any)=>t.name)).toEqual(['One','Two']);
 const one=stored.tables[0].id,two=stored.tables[1].id;
 await a.get('[data-saved-table]').setValue(one);await flushPromises();
 expect(JSON.parse(localStorage.getItem(key)!).tables).toHaveLength(2);
 // A stale tab must load the latest definition when switching.
 stored.tables.find((t:any)=>t.id===two).name='Two externally updated';localStorage.setItem(key,JSON.stringify(stored));
 await a.get('[data-saved-table]').setValue(two);await flushPromises();
 expect(a.get('[data-table-name]').element).toHaveProperty('value','Two externally updated');
 await b.get('[data-table-name]').setValue('Local draft');await b.get('[data-save-table]').trigger('click');await flushPromises();
 expect(b.get('[data-table-storage-error]').text()).toContain('其他标签页');
 expect(b.get('[data-table-name]').element).toHaveProperty('value','Local draft');
 await b.get('[data-delete-table]').trigger('click');await b.get('[data-discard-table-changes]').trigger('click');await flushPromises();
 expect(JSON.parse(localStorage.getItem(key)!).tables).toHaveLength(2);
 // Deletion elsewhere must not be silently undone by a stale save.
 stored=JSON.parse(localStorage.getItem(key)!);stored.tables=stored.tables.filter((t:any)=>t.id!==one);stored.activeId=two;localStorage.setItem(key,JSON.stringify(stored));
 const c=mount(ActivityComparison,{props:props()});await flushPromises();
 stored.tables=[];stored.activeId=null;localStorage.setItem(key,JSON.stringify(stored));
 await c.get('[data-save-table]').trigger('click');await flushPromises();
 expect(c.get('[data-table-storage-error]').text()).toContain('其他标签页');expect(JSON.parse(localStorage.getItem(key)!).tables).toHaveLength(0);
 expect(lock).toHaveBeenCalled();a.unmount();b.unmount();c.unmount();
});

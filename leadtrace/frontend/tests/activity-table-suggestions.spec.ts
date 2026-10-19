import {flushPromises,mount} from '@vue/test-utils';
import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import ActivityComparison from '../src/review/paper/ActivityComparison.vue';
import {tableStorageKey} from '../src/review/paper/activityTableBuilder';
import {activities,compounds,ids,installReviewer,response,workspace} from './paper-science-v2-fixtures';
const first={...activities[0]!,assay_name:'A'},second={...first,id:ids.activities[1]!,compound_id:compounds[1]!.id};
const third={...first,id:'30000000-0000-4000-8000-000000000093',assay_name:'B'};
const payload=(records=[first,second,third])=>({workspace_id:ids.workspace,workspace_version:1,compounds,activities:records});
const key=()=>tableStorageKey('reviewer',ids.workspace);
const read=()=>JSON.parse(localStorage.getItem(key())!);
const props=()=>({workspace:workspace() as any,active:true});
function install(){return vi.stubGlobal('fetch',vi.fn(async()=>response(payload())));}
beforeEach(()=>{installReviewer();localStorage.clear();install();});
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});
it('creates and saves initial tables, with exact records and no scientific writes',async()=>{
 const w=mount(ActivityComparison,{props:props()});await flushPromises();
 expect(w.findAll('[data-comparison-column]')).toHaveLength(1);expect(w.findAll('[data-comparison-row]')).toHaveLength(2);
 expect(read().tables).toHaveLength(2);expect(read().tables[0].name).toBe('推荐表 1');
 expect(w.get('[data-suggestion-summary]').text()).toContain('1 列');
 expect(w.get('[data-configured-columns]').isVisible()).toBe(false);
 await w.get('[data-table-name]').setValue('Reviewed');await w.get('[data-save-table]').trigger('click');await flushPromises();
 const saved=localStorage.getItem(key());w.unmount();
 const again=mount(ActivityComparison,{props:props()});await flushPromises();
 expect(again.get('[data-table-name]').element).toHaveProperty('value','Reviewed');expect(localStorage.getItem(key())).toBe(saved);
 expect(vi.mocked(fetch).mock.calls.every(call=>!call[1]?.method||call[1].method==='GET')).toBe(true);again.unmount();
});
it('appends only unrepresented measurements and preserves unsaved settings',async()=>{
 const w=mount(ActivityComparison,{props:props()});await flushPromises();
 const original=read().tables;
 await w.get('[data-table-name]').setValue('Unsaved title');
 vi.mocked(fetch).mockImplementation(async()=>response(payload([...payload().activities,{...first,id:'30000000-0000-4000-8000-000000000094',assay_name:'New'}])));
 await w.get('[data-comparison-refresh]').trigger('click');await flushPromises();
 expect(read().tables).toEqual(original);
 await w.get('[data-generate-tables]').trigger('click');await flushPromises();
 expect(read().tables).toHaveLength(3);expect(read().tables.slice(0,2)).toEqual(original);
 expect(w.get('[data-table-name]').element).toHaveProperty('value','Unsaved title');
 const saved=localStorage.getItem(key());await w.get('[data-generate-tables]').trigger('click');await flushPromises();
 expect(localStorage.getItem(key())).toBe(saved);expect(w.get('[role=status]').text()).toContain('没有新的测定列');w.unmount();
});
it('respects intentionally empty settings and never regenerates deleted tables on refresh',async()=>{
 localStorage.setItem(key(),JSON.stringify({version:1,tables:[],activeId:null}));
 const w=mount(ActivityComparison,{props:props()});await flushPromises();expect(w.findAll('[data-comparison-row]')).toHaveLength(0);
 await w.get('[data-generate-tables]').trigger('click');await flushPromises();expect(read().tables).toHaveLength(2);
 for(let i=0;i<2;i++){await w.get('[data-delete-table]').trigger('click');await w.get('[data-discard-table-changes]').trigger('click');await flushPromises();}
 await w.get('[data-comparison-refresh]').trigger('click');await flushPromises();expect(read().tables).toHaveLength(0);w.unmount();
});
it('does not replace a table draft typed while the initial data request is pending',async()=>{
 let finish!:(value:Response)=>void;vi.mocked(fetch).mockImplementation(()=>new Promise(resolve=>{finish=resolve;}));
 const w=mount(ActivityComparison,{props:props()});await w.get('[data-table-name]').setValue('My draft');finish(response(payload()));await flushPromises();
 expect(localStorage.getItem(key())).toBeNull();expect(w.get('[data-table-name]').element).toHaveProperty('value','My draft');w.unmount();
});
it('reports automatic save failures without claiming success and can retry explicitly',async()=>{
 const spy=vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw Error('quota');});
 const w=mount(ActivityComparison,{props:props()});await flushPromises();expect(w.get('[data-table-storage-error]').text()).toContain('未能保存');
 expect(localStorage.getItem(key())).toBeNull();spy.mockRestore();
 await w.get('[data-generate-tables]').trigger('click');await flushPromises();expect(read().tables).toHaveLength(2);w.unmount();
});
it('rechecks latest storage under the lock so simultaneous first loads cannot duplicate or overwrite tables',async()=>{
 const queue:Array<()=>void>=[];
 vi.stubGlobal('navigator',{locks:{request:vi.fn((_key:string,run:()=>void)=>new Promise<void>(resolve=>queue.push(()=>{run();resolve();})))}});
 const a=mount(ActivityComparison,{props:props()}),b=mount(ActivityComparison,{props:props()});await flushPromises();
 expect(queue).toHaveLength(2);queue[0]!();await flushPromises();const saved=localStorage.getItem(key());queue[1]!();await flushPromises();
 expect(localStorage.getItem(key())).toBe(saved);expect(read().tables).toHaveLength(2);
 expect(b.findAll('[data-comparison-row]')).toHaveLength(2);a.unmount();b.unmount();
});
it('keeps malformed settings intact and reports unreadable storage',async()=>{
 localStorage.setItem(key(),'{broken');const w=mount(ActivityComparison,{props:props()});await flushPromises();
 expect(localStorage.getItem(key())).toBe('{broken');expect(w.get('[data-table-storage-error]').text()).toContain('无法读取');w.unmount();
});
it('retains same-table conflict protection when appending suggestions during a dirty edit',async()=>{
 const w=mount(ActivityComparison,{props:props()});await flushPromises();await w.get('[data-table-name]').setValue('My dirty draft');
 const external=read();external.tables[0].name='Changed in another tab';localStorage.setItem(key(),JSON.stringify(external));
 vi.mocked(fetch).mockImplementation(async()=>response(payload([...payload().activities,{...first,id:'30000000-0000-4000-8000-000000000095',assay_name:'New'}])));
 await w.get('[data-comparison-refresh]').trigger('click');await flushPromises();await w.get('[data-generate-tables]').trigger('click');await flushPromises();
 expect(read().tables).toHaveLength(3);await w.get('[data-save-table]').trigger('click');await flushPromises();
 expect(w.get('[data-table-storage-error]').text()).toContain('其他标签页');
 expect(read().tables[0].name).toBe('Changed in another tab');w.unmount();
});
it('invalidates queued automatic generation when changing workspaces',async()=>{
 const queue:Array<()=>void>=[];
 vi.stubGlobal('navigator',{locks:{request:vi.fn((_key:string,run:()=>void)=>new Promise<void>(resolve=>queue.push(()=>{run();resolve();})))}});
 const w=mount(ActivityComparison,{props:props()});await flushPromises();expect(queue).toHaveLength(1);
 const nextId='30000000-0000-4000-8000-000000000099';
 vi.mocked(fetch).mockImplementation(async()=>response({...payload([]),workspace_id:nextId}));
 await w.setProps({workspace:{...workspace(),id:nextId} as any});await flushPromises();queue[0]!();await flushPromises();
 expect(localStorage.getItem(key())).toBeNull();expect(localStorage.getItem(tableStorageKey('reviewer',nextId))).toBeNull();w.unmount();
});
it('reports partial generation at the saved table limit without dropping existing tables',async()=>{
 const tables=Array.from({length:49},(_,i)=>({id:'saved-'+i,name:'Existing '+i,columns:[],mode:'any',sort:'label'}));
 localStorage.setItem(key(),JSON.stringify({version:1,tables,activeId:tables[0]!.id}));
 const w=mount(ActivityComparison,{props:props()});await flushPromises();await w.get('[data-generate-tables]').trigger('click');await flushPromises();
 expect(read().tables).toHaveLength(50);expect(read().tables.slice(0,49)).toEqual(tables);
 expect(w.get('[role=status]').text()).toContain('另有 1 列未生成');w.unmount();
});
it('shows saved table counts using that table row mode',async()=>{
 let w=mount(ActivityComparison,{props:props()});await flushPromises();const saved=read();w.unmount();
 saved.tables[0].columns.push(...saved.tables[1].columns);saved.tables[0].mode='all';localStorage.setItem(key(),JSON.stringify(saved));
 w=mount(ActivityComparison,{props:props()});await flushPromises();
 expect(w.findAll('[data-comparison-row]')).toHaveLength(1);
 expect(w.findAll('[data-saved-table] option')[1]!.text()).toContain('2 列 / 1 个 Compound');w.unmount();
});

import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import ActivityComparison from '../src/review/paper/ActivityComparison.vue';
import { activities, compounds, evidence, ids, installReviewer, response, workspace, addComparisonColumn } from './paper-science-v2-fixtures';
import { tableStorageKey } from '../src/review/paper/activityTableBuilder';
const first={...activities[0]!,value:'0.123456789012345678901',context:'100 nM, 24 h',review_hint:'Verify'};
const second={...first,id:ids.activities[1]!,compound_id:ids.compounds[1]!,context:'1000 nM, 24 h',value:'2'};
const third={...first,id:'30000000-0000-4000-8000-000000000093',assay_name:'Assay B',unit:'μM',value:'3'};
const column={id:'column-a',label:'100 nM',assay:first.assay_name,metric:first.metric,unit:first.unit,activity_ids:[first.id]};
const original=()=>({id:'30000000-0000-4000-8000-000000000080',paper_id:ids.paper,workspace_id:ids.workspace,name:'Table 1',kind:'source',source_label:'Table 1',source_title:'Potency',page_number:3,review_hint:null,review_status:'draft',created_by_kind:'ai',columns:[column],mode:'any',sort:'label'});
function install(initial:any[]=[original()],library:any[]=[{...evidence,kind:'table',bbox:{x0:0.1,y0:0.1,x1:0.9,y1:0.8}}]) {
 let version=1;let tables=structuredClone(initial);const writes:any[]=[];
 const fetcher=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
  const path=String(input),method=init?.method??'GET';
  if(method!=='GET'){
   const body=JSON.parse(String(init?.body));writes.push({path,method,body});
   if(body.expected_workspace_version!==version)return response({error:{code:'WORKSPACE_VERSION_CONFLICT',message:'Stale'}},409);
   version++;
   const id=path.split('/').at(path.endsWith('/confirm')?-2:-1)!;
   if(method==='DELETE'){tables=tables.filter(t=>t.id!==id);return response({workspace_version:version,deleted_table_id:id});}
   const table=path.endsWith('/confirm')?{...tables.find(t=>t.id===id),review_status:body.review_status}:{...original(),...body,id,review_status:'draft',created_by_kind:'human'};
   tables=tables.filter(t=>t.id!==id).concat(table);return response({workspace_version:version,table});
  }
  if(path.endsWith('/evidence'))return response({workspace_id:ids.workspace,total:library.length,workspace_version:version,items:library});
  if(path.endsWith('/activity-tables'))return response({workspace_id:ids.workspace,workspace_version:version,tables,other_activity_ids:[first,second,third].filter(a=>!tables.some(t=>t.columns.some((c:any)=>c.activity_ids.includes(a.id)))).map(a=>a.id)});
  return response({workspace_id:ids.workspace,workspace_version:version,compounds,activities:[first,second,third]});
 });vi.stubGlobal('fetch',fetcher);return {fetcher,writes,external:(next:any[])=>{tables=next;version++;}};
}
const props=()=>({workspace:workspace() as any,active:true});
beforeEach(()=>{installReviewer();localStorage.clear();});afterEach(()=>vi.unstubAllGlobals());
it('reads original source tables and a permanent Other without writing on browsing',async()=>{
 const api=install();const w=mount(ActivityComparison,{props:props()});await flushPromises();
 expect(w.get('[data-table-source]').text()).toContain('Table 1');expect(w.get('[data-table-source]').text()).toContain('Potency');
 expect(w.findAll('[data-comparison-activity]')).toHaveLength(1);expect(w.get('[data-comparison-activity]').text()).toContain(first.value);
 await w.get('[data-saved-table]').setValue('other');await flushPromises();
 expect(w.findAll('[data-comparison-activity]').map(x=>x.attributes('data-activity-id'))).toEqual(expect.arrayContaining([second.id,third.id]));
 expect(w.find('[data-delete-table]').exists()).toBe(false);expect(w.find('[data-save-table]').exists()).toBe(false);expect(api.writes).toHaveLength(0);w.unmount();
});
it('saves source metadata and explicit record IDs on the server with the loaded version',async()=>{
 const api=install([]);const w=mount(ActivityComparison,{props:props()});await flushPromises();await w.get('[data-new-table]').trigger('click');
 await addComparisonColumn(w,first,'Activity');await w.get('[data-table-name]').setValue('Primary');await w.get('[data-table-kind]').setValue('source');await w.get('[data-source-label]').setValue('Table 2');
 await w.get('[data-save-table]').trigger('click');await flushPromises();
 expect(api.writes[0].body).toMatchObject({expected_workspace_version:1,name:'Primary',kind:'source',source_label:'Table 2',columns:[{activity_ids:[first.id,second.id]}]});
 expect(JSON.stringify(api.writes)).not.toContain(first.value);expect(w.emitted('mutated')).toHaveLength(1);expect(w.text()).toContain('已保存到文章工作区');w.unmount();
});
it('requires explicit confirmation after AI revisions and after editing table configuration',async()=>{
 const api=install([{...original(),evidence_ids:[evidence.id]}]);const w=mount(ActivityComparison,{props:props()});await flushPromises();expect(w.find('[data-confirm-table]').exists()).toBe(true);
 await w.get('[data-confirm-table]').trigger('click');await flushPromises();expect(api.writes[0].body.review_status).toBe('reviewer_confirmed');
 expect(w.find('[data-confirm-table]').exists()).toBe(false);await w.get('[data-table-name]').setValue('Changed');await w.get('[data-save-table]').trigger('click');await flushPromises();
 expect(w.find('[data-confirm-table]').exists()).toBe(true);w.unmount();
});
it('rejects stale writes without replacing the local draft or rebasing it during refresh',async()=>{
 const api=install();const w=mount(ActivityComparison,{props:props()});await flushPromises();await w.get('[data-table-name]').setValue('Local draft');api.external([{...original(),name:'External'}]);
 await w.get('[data-comparison-refresh]').trigger('click');await flushPromises();await w.get('[data-save-table]').trigger('click');await flushPromises();
 expect(api.writes[0].body.expected_workspace_version).toBe(1);expect(w.get('[data-table-name]').element).toHaveProperty('value','Local draft');expect(w.get('[data-table-storage-error]').text()).toContain('版本');w.unmount();
});
it('imports local configs explicitly as custom tables, retaining the browser copy',async()=>{
 const api=install([]);const key=tableStorageKey('reviewer',ids.workspace);const old=JSON.stringify({version:1,activeId:'legacy',tables:[{id:'legacy',name:'Recommended',columns:[{...column,activityIds:null,activity_ids:undefined}],mode:'any',sort:'label'}]});localStorage.setItem(key,old);
 const w=mount(ActivityComparison,{props:props()});await flushPromises();expect(api.writes).toHaveLength(0);await w.get('[data-import-local-tables]').trigger('click');await flushPromises();
 expect(api.writes[0].body).toMatchObject({kind:'custom',source_label:null,columns:[{activity_ids:[first.id,second.id]}]});expect(localStorage.getItem(key)).toBe(old);w.unmount();
});
it('opens exact activity and preserves navigation state without writes',async()=>{
 const api=install();const w=mount(ActivityComparison,{props:props()});await flushPromises();await w.get('[data-comparison-search]').setValue('C1');await w.get('[data-comparison-activity]').trigger('click');
 expect(w.emitted('open')?.[0]).toEqual([first.compound_id,first.id]);await w.setProps({active:false});await w.setProps({active:true});await flushPromises();expect(w.get('[data-comparison-search]').element).toHaveProperty('value','C1');expect(api.writes).toHaveLength(0);w.unmount();
});
it('provides read-only admin and submitted table views',async()=>{
 const api=install();const w=mount(ActivityComparison,{props:{...props(),readOnly:true}});await flushPromises();
 expect(w.find('[data-save-table]').exists()).toBe(false);expect(w.find('[data-confirm-table]').exists()).toBe(false);expect(w.find('[data-new-table]').exists()).toBe(false);expect(w.find('[data-column-edit]').exists()).toBe(false);expect(w.find('[data-comparison-activity]').exists()).toBe(true);expect(api.writes).toHaveLength(0);w.unmount();
});
it('supports unresolved table interpretation and editable review notes',async()=>{
 const api=install();const w=mount(ActivityComparison,{props:props()});await flushPromises();
 await w.get('[data-table-review-hint]').setValue('Source grouping cannot be determined');await w.get('[data-save-table]').trigger('click');await flushPromises();
 expect(api.writes[0].body.review_hint).toContain('cannot be determined');await w.get('[data-unresolve-table]').trigger('click');await flushPromises();
 expect(api.writes[1].body.review_status).toBe('unresolved');expect(w.get('[data-table-review-status]').text()).toContain('无法判定');w.unmount();
});
it('ignores an in-flight save result after account changes within the same workspace',async()=>{
 const {useAuthStore}=await import('../src/auth/store');const api=install();let finish!:(r:Response)=>void;
 const originalFetch=api.fetcher.getMockImplementation()!;api.fetcher.mockImplementation((input,init)=>init?.method==='PUT'?new Promise(resolve=>{finish=resolve;}):originalFetch(input,init));
 const w=mount(ActivityComparison,{props:props()});await flushPromises();await w.get('[data-table-name]').setValue('Old account draft');await w.get('[data-save-table]').trigger('click');
 const auth=useAuthStore();auth.user={...auth.user!,username:'another-reviewer'};await flushPromises();finish(response({workspace_version:2,table:{...original(),name:'Old account draft'}}));await flushPromises();
 expect(w.get('[data-table-name]').element).toHaveProperty('value','Table 1');expect(w.emitted('mutated')).toBeUndefined();w.unmount();
});
it('loads an explicitly requested source table and guards unsaved switches',async()=>{
 install([original(),{...original(),id:'30000000-0000-4000-8000-000000000081',name:'Table 2'}]);const w=mount(ActivityComparison,{props:{...props(),selectedTableId:'30000000-0000-4000-8000-000000000081'}});await flushPromises();
 expect(w.get('[data-table-name]').element).toHaveProperty('value','Table 2');await w.get('[data-table-name]').setValue('Draft');await w.setProps({selectedTableId:original().id});
 expect(w.get('[data-table-name]').element).toHaveProperty('value','Draft');await w.get('[data-discard-table-changes]').trigger('click');expect(w.get('[data-table-name]').element).toHaveProperty('value','Table 1');w.unmount();
});

it('removes only the selected row memberships and preserves explicit empty rows and manual order',async()=>{
 const api=install([{...original(),sort:'default',compound_ids:[compounds[1]!.id,compounds[0]!.id],columns:[{...column,activity_ids:[first.id,second.id]}]}]);
 const w=mount(ActivityComparison,{props:props()});await flushPromises();
 expect(w.findAll('[data-comparison-row]').map(x=>x.attributes('data-compound-id'))).toEqual([compounds[1]!.id,compounds[0]!.id]);
 await w.get('[data-toggle-row-config]').trigger('click');await w.findAll('[data-row-remove]')[0]!.trigger('click');
 await w.get('[data-add-row-select]').setValue(compounds[2]!.id);await w.get('[data-add-row]').trigger('click');
 await w.findAll('[data-row-up]')[1]!.trigger('click');await w.get('[data-save-table]').trigger('click');await flushPromises();
 expect(api.writes[0].body).toMatchObject({compound_ids:[compounds[2]!.id,compounds[0]!.id],sort:'default',columns:[{activity_ids:[first.id]}]});
 expect(w.findAll('[data-comparison-row]')).toHaveLength(2);
 await w.get('[data-saved-table]').setValue('other');await flushPromises();expect(w.find(`[data-activity-id="${second.id}"]`).exists()).toBe(true);w.unmount();
});
it('requires a source screenshot to confirm and saves selected evidence separately from scientific values',async()=>{
 const api=install();const w=mount(ActivityComparison,{props:props()});await flushPromises();
 expect(w.get('[data-confirm-table]').attributes('disabled')).toBeDefined();expect(w.find('[data-table-evidence-missing]').exists()).toBe(true);
 await w.get('[data-table-evidence-choice]').setValue(true);await w.get('[data-save-table]').trigger('click');await flushPromises();
 expect(api.writes[0].body.evidence_ids).toEqual([evidence.id]);expect(w.get('[data-confirm-table]').attributes('disabled')).toBeUndefined();
 expect(w.find('[data-table-evidence-image]').exists()).toBe(true);w.unmount();
});
it('keeps the active table while Evidence editing is open and searches existing Compounds before adding rows',async()=>{
 install();const w=mount(ActivityComparison,{props:props()});await flushPromises();
 await w.get('[data-manage-table-evidence]').trigger('click');await flushPromises();
 await w.get('[data-saved-table]').setValue('other');expect(w.find('[data-table-source]').exists()).toBe(true);
 expect(w.get('[data-new-table]').attributes('disabled')).toBeDefined();
 await w.get('[data-manage-table-evidence]').trigger('click');await w.get('[data-toggle-row-config]').trigger('click');
 await w.get('[data-add-row-search]').setValue(compounds[2]!.compound_label);
 expect(w.findAll('[data-add-row-select] option').map(x=>x.attributes('value'))).toEqual(['',compounds[2]!.id]);w.unmount();
});

it('preserves linked screenshot order and keeps read-only navigation usable after sorting',async()=>{
 const firstEvidence={...evidence,kind:'table',bbox:{x0:.1,y0:.1,x1:.9,y1:.9},caption:'First page'};
 const nextEvidence={...firstEvidence,id:ids.evidence[1],page_number:3,caption:'Second page'};
 install([{...original(),evidence_ids:[nextEvidence.id,firstEvidence.id]}],[firstEvidence,nextEvidence]);
 const w=mount(ActivityComparison,{props:{...props(),readOnly:true}});await flushPromises();
 expect(w.findAll('[data-table-evidence-image] p').map(x=>x.text())).toEqual(['p3 · Second page','p2 · First page']);
 await w.get('[data-comparison-sort]').setValue('default');await w.get('[data-comparison-activity]').trigger('click');expect(w.emitted('open')?.[0]).toEqual([first.compound_id,first.id]);w.unmount();
});

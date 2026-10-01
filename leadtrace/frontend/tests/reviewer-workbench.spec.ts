import type { PaperWorkspace } from '../src/v2/types';
import { flushPromises } from '@vue/test-utils';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ids, installReviewer, mountWorkspace, response, workspace } from './paper-science-v2-fixtures';
beforeEach(installReviewer);
afterEach(()=>vi.unstubAllGlobals());
it('sends versioned article metadata without a separate bibliography viewed state',async()=>{
  const writes:{path:string;body:any;headers:Headers}[]=[];
  let ws={...workspace(),sections:workspace().sections.map(x=>({...x,state:"pending" as const}))};
  const item={kind:'compound',entity_id:ids.compounds[0],section_key:'compounds',label:'Paper',signature:'a'.repeat(64),viewed:false};
  const progress=()=>({workspace_id:ws.id,workspace_version:ws.version,tracking_started:item.viewed,items:[item],sections:ws.sections.map(x=>({...x,total:x.section_key==='compounds'?1:0,viewed:item.viewed&&x.section_key==='compounds'?1:0,complete:item.viewed&&x.section_key==='compounds'}))});
  vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=new URL(String(input),'http://test').pathname;
    if(init?.method&&init.method!=='GET') writes.push({path,body:JSON.parse(String(init.body)),headers:new Headers(init.headers)});
    if(path.endsWith('/review-progress'))return response(progress());
    if(path.endsWith('/views')){item.viewed=true;return response(progress());}
    if(path.endsWith('/bibliography')){const {expected_workspace_version,...fields}=JSON.parse(String(init!.body));ws={...ws,version:expected_workspace_version+1,bibliography:{...ws.bibliography,...fields}};return response(ws);}
    return response(ws);
  }));
  const {wrapper}=await mountWorkspace('bibliography');
  expect(writes).toHaveLength(0);
  const details=wrapper.get('[data-bibliography-detail]');(details.element as HTMLDetailsElement).open=true;await details.trigger('toggle');await flushPromises();
  expect(writes).toHaveLength(0);
  expect(ws.version).toBe(1);
  expect(wrapper.get('[data-section-key="bibliography"]').attributes('data-state')).toBe('pending');
  await wrapper.get('[data-edit-bibliography]').trigger('click');
  await wrapper.get('[data-abstract-input]').setValue('Source abstract, preserved verbatim.');
  await wrapper.get('[data-add-pdb]').trigger('click');
  await wrapper.get('[data-pdb-id]').setValue('1ABC');
  await wrapper.get('form.bibliography-edit-form').trigger('submit');await flushPromises();
  expect(writes.at(-1)?.body).toMatchObject({expected_workspace_version:1,abstract:'Source abstract, preserved verbatim.',pdb_references:[{pdb_id:'1ABC',usage:'unknown'}]});
  expect(writes.at(-1)?.headers.get('X-CSRF-Token')).toBe('reviewer-csrf');
  wrapper.unmount();
});

it('records a Compound selection without separate structure receipts, including delayed hidden loads',async()=>{
  const {compounds}=await import('./paper-science-v2-fixtures');
  const ws=workspace(),cid=compounds[0]!.id;
  let finish:((value:Response)=>void)|undefined;
  const pending=new Promise<Response>(resolve=>{finish=resolve;});
  const writes:any[]=[];
  const item={kind:'compound',entity_id:cid,section_key:'compounds',label:'1',signature:'a'.repeat(64),viewed:false};
  const progress=()=>({workspace_id:ws.id,workspace_version:1,tracking_started:item.viewed,items:[item],sections:[]});
  vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=new URL(String(input),'http://test').pathname;
    if(path.endsWith('/review-progress'))return response(progress());
    if(path.endsWith('/views')){writes.push(JSON.parse(String(init?.body)));item.viewed=true;return response(progress());}
    if(path.endsWith('/compounds'))return response({workspace_id:ws.id,workspace_version:1,items:compounds,total:compounds.length});
    if(path.endsWith('/lineages'))return response({workspace_id:ws.id,workspace_version:1,items:[],total:0});
    if(path===`/api/v2/compounds/${cid}/structure`)return pending;
    return response(ws);
  }));
  const {wrapper}=await mountWorkspace('compounds');
  const details=wrapper.get('.compound-detail-panel > details');(details.element as HTMLDetailsElement).open=true;await details.trigger('toggle');
  await wrapper.findAll('[data-workspace-tab]')[2]!.trigger('click');await flushPromises();
  finish!(response({workspace_version:1,structure:null}));await flushPromises();
  expect(writes).toHaveLength(0);
  await wrapper.findAll('[data-workspace-tab]')[1]!.trigger('click');await flushPromises();
  expect(writes).toHaveLength(0);
  await wrapper.get(`[data-compound-id="${cid}"] button`).trigger('click');await flushPromises();
  expect(writes).toHaveLength(1);expect(writes[0].kind).toBe('compound');
  wrapper.unmount();
});

it('does not create separate Evidence viewed receipts',async()=>{
  const {defineComponent,h,ref}=await import('vue');
  const {mount}=await import('@vue/test-utils');
  const {provideReviewProgress}=await import('../src/review/paper/useReviewProgress');
  const {default:EvidenceExcerpt}=await import('../src/review/paper/EvidenceExcerpt.vue');
  const ws=workspace(2) as PaperWorkspace,contentVersion=ref(1),quote=ref('Old evidence');
  const writes:any[]=[];
  const item={kind:'lineage',entity_id:ids.lineages[0],section_key:'lineages',label:'Evidence',signature:'b'.repeat(64),viewed:false};
  const progress=()=>({workspace_id:ws.id,workspace_version:2,tracking_started:item.viewed,items:[item],sections:[]});
  vi.stubGlobal('fetch',vi.fn(async(_input:RequestInfo|URL,init?:RequestInit)=>{if(init?.method==='POST'){writes.push(JSON.parse(String(init.body)));item.viewed=true;}return response(progress());}));
  const Host=defineComponent({setup(){provideReviewProgress(()=>ws,()=>true);return()=>h(EvidenceExcerpt,{workspace:ws,contentVersion:contentVersion.value,evidence:{id:ids.evidence[0],paper_id:ids.paper,workspace_id:ids.workspace,kind:'text',source_sha256:'a'.repeat(64),page_number:1,bbox:null,quoted_text:quote.value,caption:null,reviewer_note:null,crop_asset_id:null}});}});
  const wrapper=mount(Host);await flushPromises();
  const details=wrapper.get('details');(details.element as HTMLDetailsElement).open=true;await details.trigger('toggle');await flushPromises();expect(writes).toHaveLength(0);
  contentVersion.value=2;quote.value='Updated evidence';await flushPromises();
  (details.element as HTMLDetailsElement).open=false;await details.trigger('toggle');(details.element as HTMLDetailsElement).open=true;await details.trigger('toggle');await flushPromises();
  expect(wrapper.text()).toContain('Updated evidence');expect(writes).toHaveLength(0);expect(wrapper.find('[data-viewed]').exists()).toBe(false);wrapper.unmount();
});


it('rejects a stale Compound detail version before recording its group signature',async()=>{
  const {defineComponent,h,ref}=await import('vue');
  const {mount}=await import('@vue/test-utils');
  const {provideReviewProgress}=await import('../src/review/paper/useReviewProgress');
  const ws=workspace(2) as PaperWorkspace,version=ref(1),writes:any[]=[];
  const item={kind:'compound',entity_id:ids.compounds[0],section_key:'compounds',label:'1',signature:'c'.repeat(64),viewed:false};
  const progress=()=>({workspace_id:ws.id,workspace_version:2,tracking_started:item.viewed,items:[item],sections:[]});
  vi.stubGlobal('fetch',vi.fn(async(_input:RequestInfo|URL,init?:RequestInit)=>{if(init?.method==='POST'){writes.push(JSON.parse(String(init.body)));item.viewed=true;}return response(progress());}));
  const wrapper=mount(defineComponent({setup(){const state=provideReviewProgress(()=>ws,()=>true);return()=>h('button',{onClick:()=>state.view('compound',item.entity_id,true,version.value)},'Open Compound');}}));
  await flushPromises();await wrapper.get('button').trigger('click');await flushPromises();expect(writes).toHaveLength(0);
  version.value=2;await wrapper.get('button').trigger('click');await flushPromises();expect(writes).toHaveLength(1);expect(writes[0].signature).toBe('c'.repeat(64));wrapper.unmount();
});

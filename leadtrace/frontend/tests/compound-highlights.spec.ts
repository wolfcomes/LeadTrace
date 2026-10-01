import { defineComponent,h } from 'vue';
import { mount,flushPromises } from '@vue/test-utils';
import { beforeEach,afterEach,it,expect,vi } from 'vitest';
import { compounds,evidence,workspace,ids,installReviewer,response } from './paper-science-v2-fixtures';
import { provideHighlights } from '../src/review/paper/useHighlights';
import HighlightEditor from '../src/review/paper/HighlightEditor.vue';
import { setLocale } from '../src/i18n';
import type { PaperWorkspace } from '../src/v2/types';
beforeEach(()=>{installReviewer();setLocale('zh-CN');});
afterEach(()=>{vi.unstubAllGlobals();setLocale('zh-CN');});
function host(readOnly=false) {
 return defineComponent({setup(){const ws=workspace() as PaperWorkspace;provideHighlights(()=>ws);return()=>h(HighlightEditor,{workspace:ws,readOnly});}});
}
function mock(conflict=false){
 const writes:any[]=[],items:any[]=[];
 vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
  const path=new URL(String(input),'http://test').pathname;
  if(path.endsWith('/compounds'))return response({workspace_id:ids.workspace,workspace_version:1,items:compounds,total:compounds.length});
  if(path.endsWith('/evidence'))return response({workspace_id:ids.workspace,workspace_version:1,items:[evidence],total:1});
  if(init?.method==='POST'||init?.method==='PATCH'){
   const body=JSON.parse(String(init.body));writes.push({body,headers:new Headers(init.headers)});
   if(conflict)return response({code:'WORKSPACE_VERSION_CONFLICT',message:'changed',request_id:'test'},409);
   const {expected_workspace_version,...fields}=body;
   const item={...fields,id:ids.activities[0],paper_id:ids.paper,workspace_id:ids.workspace,created_by_kind:'reviewer'};if(init?.method==='PATCH')items[0]=item;else items.push(item);
   return response({highlight:items[0],workspace_version:2});
  }
  return response({workspace_id:ids.workspace,workspace_version:items.length?2:1,items,total:items.length});
 }));return writes;
}
async function fill(wrapper:ReturnType<typeof mount>){
 await wrapper.get('[data-add-highlight]').trigger('click');
 await wrapper.get('[data-highlight-compound]').setValue(ids.compounds[0]);
 await wrapper.get('[data-highlight-evidence]').setValue(ids.evidence[0]);
 await wrapper.get('[data-highlight-role]').setValue('paper_selected');
 await wrapper.get('[data-highlight-scope]').setValue('Series A');
 await wrapper.get('[data-highlight-rationale]').setValue('Synthetic source-supported author choice');
}
it('saves source-linked draft roles with CSRF and version, preserving input when language changes',async()=>{
 const writes=mock();const wrapper=mount(host());await flushPromises();
 expect(wrapper.text()).toContain('不代表文章没有此类分子');expect(writes).toHaveLength(0);
 await fill(wrapper);setLocale('en');await flushPromises();
 expect((wrapper.get('[data-highlight-rationale]').element as HTMLTextAreaElement).value).toContain('Synthetic');
 await wrapper.get('form').trigger('submit');await flushPromises();
 expect(writes[0].body).toMatchObject({compound_id:ids.compounds[0],evidence_id:ids.evidence[0],review_status:'draft',expected_workspace_version:1,role:'paper_selected'});
 expect(writes[0].headers.get('X-CSRF-Token')).toBe('reviewer-csrf');
 expect(wrapper.text()).toContain('Paper-prioritized compound');expect(wrapper.text()).toContain('Annotation awaiting review');wrapper.unmount();
});
it('keeps unsaved fields on version conflicts and offers no mutations in read-only mode',async()=>{
 mock(true);const wrapper=mount(host());await flushPromises();await fill(wrapper);await wrapper.get('form').trigger('submit');await flushPromises();
 expect(wrapper.find('form').exists()).toBe(true);expect((wrapper.get('[data-highlight-scope]').element as HTMLInputElement).value).toBe('Series A');expect(wrapper.text()).toContain('当前输入已保留');wrapper.unmount();
 const readonly=mount(host(true));await flushPromises();expect(readonly.find('[data-add-highlight]').exists()).toBe(false);readonly.unmount();
});

it('requires a fresh review disposition after editing a confirmed assertion',async()=>{
 mock();const wrapper=mount(host());await flushPromises();await fill(wrapper);
 await wrapper.get('select[data-highlight-status]').setValue('reviewer_confirmed');
 await wrapper.get('form').trigger('submit');await flushPromises();
 expect(wrapper.text()).toContain('标注已确认');
 await wrapper.findAll('.highlight-card button')[0]!.trigger('click');
 expect((wrapper.get('select[data-highlight-status]').element as HTMLSelectElement).value).toBe('reviewer_confirmed');
 await wrapper.get('[data-highlight-rationale]').setValue('Changed scientific rationale');
 expect((wrapper.get('select[data-highlight-status]').element as HTMLSelectElement).value).toBe('draft');wrapper.unmount();
});

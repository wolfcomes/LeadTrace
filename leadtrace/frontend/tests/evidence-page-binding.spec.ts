import {mount,flushPromises} from '@vue/test-utils';
import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import type {PaperWorkspace} from '../src/v2/types';
import EvidenceEditor from '../src/review/paper/EvidenceEditor.vue';
import {installReviewer,workspace,ids,response,evidence} from './paper-science-v2-fixtures';
beforeEach(installReviewer);afterEach(()=>vi.unstubAllGlobals());
it('clears an old crop when the user changes its Evidence page',async()=>{
 const writes:any[]=[];
 vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
  const path=new URL(String(input),'http://test').pathname;
  if(init?.method==='POST'){const body=JSON.parse(String(init.body));writes.push(body);return response({evidence:{...evidence,...body},workspace_version:2},201);}
  return response({workspace_id:ids.workspace,workspace_version:1,items:[],total:0});
 }));
 const wrapper=mount(EvidenceEditor,{props:{workspace:workspace() as PaperWorkspace,activityOnly:true},global:{stubs:{PdfReviewCanvas:{template:'<button data-capture @click="$emit(\'create-region\',{pageNumber:2,x0:.1,y0:.2,x1:.8,y1:.4})">Capture synthetic region</button>'}}}});
 await flushPromises();await wrapper.get('[data-add-evidence]').trigger('click');
 const open=wrapper.findAll('button').find(x=>x.text()==='从 PDF 框选')!;await open.trigger('click');
 await wrapper.get('[data-capture]').trigger('click');
 await wrapper.get('[data-evidence-page]').setValue('3');
 await wrapper.get('[data-evidence-quote]').setValue('Synthetic page 3 evidence');
 await wrapper.get('[data-save-evidence]').trigger('click');await flushPromises();
 expect(writes).toHaveLength(1);
 expect(writes[0]).toMatchObject({page_number:3,bbox:null});
 wrapper.unmount();
});

it('lets a reviewer replace an existing wrong region on a new page',async()=>{
 const writes:any[]=[];
 const original={...evidence,bbox:{x0:.05,y0:.1,x1:.2,y1:.3}};
 vi.stubGlobal('fetch',vi.fn(async(_input:RequestInfo|URL,init?:RequestInit)=>{
  if(init?.method==='PATCH'){const body=JSON.parse(String(init.body));writes.push(body);return response({evidence:{...original,...body},workspace_version:2});}
  return response({workspace_id:ids.workspace,workspace_version:1,items:[original],total:1});
 }));
 const wrapper=mount(EvidenceEditor,{props:{workspace:workspace() as PaperWorkspace,activityOnly:true},global:{stubs:{PdfReviewCanvas:{template:'<button data-recapture @click="$emit(\'create-region\',{pageNumber:4,x0:.2,y0:.3,x1:.7,y1:.6})">Capture synthetic new region</button>'}}}});
 await flushPromises();await wrapper.get('[data-edit-evidence]').trigger('click');
 await wrapper.get('form.evidence-edit-form input[type="number"]').setValue(3);
 expect(wrapper.text()).toContain('原选区已清除');
 await wrapper.get('[data-edit-evidence-region]').trigger('click');await wrapper.get('[data-recapture]').trigger('click');
 expect(wrapper.text()).not.toContain('原选区已清除');
 await wrapper.get('[data-save-evidence-edit]').trigger('click');await flushPromises();
 expect(writes[0]).toMatchObject({page_number:4,bbox:{x0:.2,y0:.3,x1:.7,y1:.6}});
 wrapper.unmount();
});

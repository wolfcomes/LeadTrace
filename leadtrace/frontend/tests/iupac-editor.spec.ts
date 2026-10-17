import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { useAuthStore } from '../src/auth/store';
import CompoundStructureEditor from '../src/review/paper/CompoundStructureEditor.vue';
import type { Compound, PaperWorkspace } from '../src/v2/types';

const compound = {id:'10000000-0000-4000-8000-000000000001',paper_id:'10000000-0000-4000-8000-000000000002',workspace_id:'10000000-0000-4000-8000-000000000003',compound_label:'1',display_name:null,description:null,sort_order:0,created_by_kind:'reviewer'} as Compound;
const source = {} as PaperWorkspace['source'];
const response = (body:unknown,status=200) => new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
const converted = {smiles:'CCO',molfile:'converted molfile',resolver:'OPSIN 2.8.0'};
function mountEditor() {return mount(CompoundStructureEditor,{props:{compound,workspaceVersion:1,source},global:{stubs:{StructureSourceImages:true,KetcherEditor:{props:['modelValue'],template:'<div data-ketcher-preview>{{modelValue}}</div>'}}}});}
beforeEach(()=>{setActivePinia(createPinia());useAuthStore().acceptSession({user:{username:'reviewer',display_name:'Reviewer',role:'reviewer',must_change_password:false},csrf_token:'csrf'});});
afterEach(()=>{useAuthStore().stopSessionSync();vi.unstubAllGlobals();});

it('loads converted structure as unsaved content with no confirmation or mutation',async()=>{
 const calls:RequestInit[]=[];
 vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{calls.push(init??{});return String(input).endsWith('/resolve-iupac')?response(converted):response({structure:null,workspace_version:1});}));
 const wrapper=mountEditor();await flushPromises();
 await wrapper.get('[data-iupac-name]').setValue('ethanol');await wrapper.get('[data-convert-iupac]').trigger('click');await flushPromises();
 expect((wrapper.get('[data-smiles-input]').element as HTMLTextAreaElement).value).toBe('CCO');
 expect(wrapper.get('[data-ketcher-preview]').text()).toContain('converted molfile');
 expect(wrapper.get('[data-confirm-structure]').attributes('disabled')).toBeDefined();
 expect(wrapper.get('[data-save-ketcher]').attributes('disabled')).toBeUndefined();
 expect(calls.filter(x=>x.method==='PUT')).toHaveLength(0);
 expect(wrapper.emitted('mutated')).toBeUndefined();
 expect(new Headers(calls.find(x=>x.method==='POST')?.headers).get('X-CSRF-Token')).toBe('csrf');
 wrapper.unmount();
});

it('leaves current unsaved input intact when conversion fails',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>String(input).endsWith('/resolve-iupac')?response({code:'IUPAC_UNPARSEABLE',message:'Cannot parse',request_id:'iupac-test'},422):response({structure:null,workspace_version:1})));
 const wrapper=mountEditor();await flushPromises();await wrapper.get('[data-smiles-input]').setValue('CCN');
 await wrapper.get('[data-iupac-name]').setValue('unparseable');await wrapper.get('[data-convert-iupac]').trigger('click');await flushPromises();
 expect((wrapper.get('[data-smiles-input]').element as HTMLTextAreaElement).value).toBe('CCN');
 expect(wrapper.get('[role=alert]').text()).toContain('无法解析');
 wrapper.unmount();
});

it('ignores a conversion response after permissions become read-only',async()=>{
 let finish!:(x:Response)=>void;const pending=new Promise<Response>(resolve=>finish=resolve);
 vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>String(input).endsWith('/resolve-iupac')?pending:response({structure:null,workspace_version:1})));
 const wrapper=mountEditor();await flushPromises();await wrapper.get('[data-iupac-name]').setValue('ethanol');await wrapper.get('[data-convert-iupac]').trigger('click');
 await wrapper.setProps({readOnly:true});finish(response(converted));await flushPromises();
 expect((wrapper.get('[data-smiles-input]').element as HTMLTextAreaElement).value).toBe('');
 expect(wrapper.find('[data-ketcher-preview]').exists()).toBe(false);wrapper.unmount();
});

it('discards a conversion when the workspace changes during the request',async()=>{
 let finish!:(x:Response)=>void;const pending=new Promise<Response>(resolve=>finish=resolve);
 vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>String(input).endsWith('/resolve-iupac')?pending:response({structure:null,workspace_version:1})));
 const wrapper=mountEditor();await flushPromises();await wrapper.get('[data-iupac-name]').setValue('ethanol');await wrapper.get('[data-convert-iupac]').trigger('click');
 await wrapper.setProps({workspaceVersion:2});finish(response(converted));await flushPromises();
 expect((wrapper.get('[data-smiles-input]').element as HTMLTextAreaElement).value).toBe('');
 expect(wrapper.get('[role=alert]').text()).toContain('内容已变化');wrapper.unmount();
});

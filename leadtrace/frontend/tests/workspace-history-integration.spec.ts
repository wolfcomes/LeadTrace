import { flushPromises, mount } from '@vue/test-utils';
import { createMemoryHistory } from 'vue-router';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import App from '../src/App.vue';
import { createAppRouter } from '../src/app/router';
import { installReviewer, response, ids, workspace, compounds } from './paper-science-v2-fixtures';

beforeEach(installReviewer);afterEach(()=>vi.unstubAllGlobals());
function mock(){let version=1;const writes:string[]=[];vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{const path=String(input);if(path.endsWith('/edit-history/undo')){writes.push(path);version++;return response({workspace_version:version,undo_action:null,redo_action:'compound.create'});}if(path.endsWith('/edit-history'))return response({workspace_version:version,undo_action:'compound.create',redo_action:null});if(path.endsWith('/compounds'))return response({workspace_id:ids.workspace,workspace_version:version,items:compounds,total:compounds.length});if(path.endsWith('/structure'))return response({workspace_version:version,structure:null});if(path.endsWith('/review-progress'))return response({},404);if(['/compound-highlights','/evidence','/activities','/source-images'].some(end=>path.endsWith(end)))return response({workspace_id:ids.workspace,workspace_version:version,compound_id:compounds[0]!.id,items:[],total:0});return response(workspace(version));}));return writes;}
async function page(tab='bibliography'){const router=createAppRouter(createMemoryHistory());await router.push(`/review/papers/${ids.paper}?workspace=${ids.workspace}&tab=${tab}`);await router.isReady();const wrapper=mount(App,{global:{plugins:[router],stubs:{KetcherEditor:true}}});await flushPromises();return {wrapper,router};}

it('blocks history during bibliography editing and remounts it after restoring',async()=>{
 const writes=mock();const {wrapper}=await page();
 expect(wrapper.get('[data-undo]').attributes('disabled')).toBeUndefined();
 await wrapper.get('[data-edit-bibliography]').trigger('click');
 await wrapper.get('.bibliography-edit-form input').setValue('Unsaved title');
 expect(wrapper.get('[data-undo]').attributes('disabled')).toBeDefined();
 await wrapper.get('[data-undo]').trigger('click');expect(writes).toHaveLength(0);
 const cancel=wrapper.findAll('.bibliography-edit-form button').find(button=>button.text()==='取消')!;await cancel.trigger('click');
 expect(wrapper.get('[data-undo]').attributes('disabled')).toBeUndefined();
 const before=wrapper.findComponent({name:'BibliographyEditor'}).vm;
 await wrapper.get('[data-undo]').trigger('click');await flushPromises();
 expect(writes).toHaveLength(1);expect(wrapper.findComponent({name:'BibliographyEditor'}).vm).not.toBe(before);
 expect(wrapper.get('[data-workspace-version]').text()).toContain('v2');wrapper.unmount();
});

it('blocks history for unsaved SMILES and while Ketcher is open',async()=>{
 mock();const {wrapper}=await page('compounds');
 expect(wrapper.get('[data-undo]').attributes('disabled')).toBeUndefined();
 await wrapper.get('[data-smiles-input]').setValue('CCN');expect(wrapper.get('[data-undo]').attributes('disabled')).toBeDefined();
 await wrapper.get('[data-smiles-input]').setValue('');expect(wrapper.get('[data-undo]').attributes('disabled')).toBeUndefined();
 await wrapper.get('[data-open-ketcher]').trigger('click');expect(wrapper.get('[data-undo]').attributes('disabled')).toBeDefined();
 await wrapper.get('[data-open-ketcher]').trigger('click');expect(wrapper.get('[data-undo]').attributes('disabled')).toBeUndefined();wrapper.unmount();
});

it('locks editing through the restore request and authoritative reload',async()=>{
 let finishUndo!:(value:Response)=>void,finishReload!:(value:Response)=>void;
 const undo=new Promise<Response>(resolve=>finishUndo=resolve),reload=new Promise<Response>(resolve=>finishReload=resolve);
 let reads=0;
 vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>{const path=String(input);if(path.endsWith('/edit-history/undo'))return undo;if(path.endsWith('/edit-history'))return response({workspace_version:1,undo_action:'compound.create',redo_action:null});if(path===`/api/v2/workspaces/${ids.workspace}`){reads++;return reads===1?response(workspace()):reload;}return response({},404);}));
 const {wrapper}=await page();await wrapper.get('[data-undo]').trigger('click');
 expect(wrapper.get('[data-edit-bibliography]').attributes('disabled')).toBeDefined();
 finishUndo(response({workspace_version:2,undo_action:null,redo_action:'compound.create'}));await flushPromises();
 expect(wrapper.get('[data-edit-bibliography]').attributes('disabled')).toBeDefined();
 finishReload(response(workspace(2)));await flushPromises();
 expect(wrapper.get('[data-edit-bibliography]').attributes('disabled')).toBeUndefined();wrapper.unmount();
});

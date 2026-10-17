import { mount, flushPromises } from '@vue/test-utils';
import { beforeEach, afterEach, it, expect, vi } from 'vitest';
import { installReviewer, response, ids } from './paper-science-v2-fixtures';
import WorkspaceHistory from '../src/review/paper/WorkspaceHistory.vue';
beforeEach(installReviewer);afterEach(()=>vi.unstubAllGlobals());
it('loads saved edit actions and submits versioned undo with csrf',async()=>{
 const calls:any[]=[];
 vi.stubGlobal('fetch',vi.fn(async(input,init)=>{calls.push({path:String(input),init});return response({workspace_version:init?.method==='POST'?3:2,undo_action:init?.method==='POST'?null:'compound.create',redo_action:init?.method==='POST'?'compound.create':null});}));
 const w=mount(WorkspaceHistory,{props:{workspaceId:ids.workspace,version:2}});await flushPromises();
 expect(w.get('[data-undo]').text()).toContain('Compound');
 await w.get('[data-undo]').trigger('click');await flushPromises();
 const write=calls.find(x=>x.init?.method==='POST');expect(write.path).toContain('/edit-history/undo');expect(JSON.parse(write.init.body)).toEqual({expected_workspace_version:2});expect(new Headers(write.init.headers).get('X-CSRF-Token')).toBe('reviewer-csrf');expect(w.emitted('restored')).toHaveLength(1);w.unmount();
});
it('disables history for readonly state and reports version conflict',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(_input,init)=>init?.method==='POST'?response({code:'WORKSPACE_VERSION_CONFLICT',message:'Changed',details:{}},409):response({workspace_version:2,undo_action:'compound.update',redo_action:null})));
 const w=mount(WorkspaceHistory,{props:{workspaceId:ids.workspace,version:2,readOnly:true}});await flushPromises();expect(w.get('[data-undo]').attributes('disabled')).toBeDefined();
 await w.setProps({readOnly:false});await w.get('[data-undo]').trigger('click');await flushPromises();expect(w.emitted('conflict')).toHaveLength(1);w.unmount();
});

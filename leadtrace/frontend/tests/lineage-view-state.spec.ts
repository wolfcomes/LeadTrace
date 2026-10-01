import { flushPromises } from '@vue/test-utils';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { compounds, ids, installReviewer, lineages, mountWorkspace, response, workspace } from './paper-science-v2-fixtures';
beforeEach(installReviewer);
afterEach(() => vi.unstubAllGlobals());
it('uses independent views and opens a compound picker from the graph without creating a record', async () => {
  const writes: string[] = [];
  vi.stubGlobal('fetch',vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input),'http://leadtrace.test').pathname;
    if(init?.method && init.method!=='GET') writes.push(path);
    if(path.endsWith('/compounds')) return response({workspace_id:ids.workspace,workspace_version:1,items:compounds,total:compounds.length});
    if(path.endsWith('/lineages')) return response({workspace_id:ids.workspace,workspace_version:1,items:lineages,total:lineages.length});
    return response(workspace());
  }));
  const {wrapper} = await mountWorkspace('lineages');
  expect(wrapper.findAll('[data-lineage-view-tab]')).toHaveLength(3);
  expect(wrapper.get('[data-lineage-view="graph"]').isVisible()).toBe(true);
  expect(wrapper.get('[data-lineage-view="compounds"]').isVisible()).toBe(false);
  await wrapper.get('[data-graph-add-node]').trigger('click');
  await flushPromises();
  expect(wrapper.get('[data-graph-compound-picker]').isVisible()).toBe(true);
  expect(writes).toHaveLength(0);
  await wrapper.get('[data-cancel-graph-node]').trigger('click');
  await wrapper.get('[data-lineage-view-tab="edges"]').trigger('click');
  expect(wrapper.get('[data-lineage-view="edges"]').isVisible()).toBe(true);
  expect(wrapper.get('[data-lineage-view="graph"]').attributes('style')).toContain('display: none');
});

it('preserves an unsaved Edge draft when returning after another tab changes the workspace',async()=>{
  let version=1;
  vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
    const path=new URL(String(input),'http://test').pathname;
    if(init?.method==='PUT'){version++;return response(workspace(version));}
    if(path.endsWith('/compounds'))return response({workspace_id:ids.workspace,workspace_version:version,items:compounds,total:compounds.length});
    if(path.endsWith('/lineages'))return response({workspace_id:ids.workspace,workspace_version:version,items:lineages,total:lineages.length});
    return response(workspace(version));
  }));
  const {wrapper}=await mountWorkspace('lineages');
  await wrapper.get('[data-lineage-view-tab="edges"]').trigger('click');
  const summary='.edge-create-form input[maxlength="10000"]';
  await wrapper.get(summary).setValue('Unsaved source comparison');
  await wrapper.findAll('[data-workspace-tab]')[0]!.trigger('click');await flushPromises();
  await wrapper.get('[data-section-key="bibliography"] [data-section-choice="not_reported"]').trigger('click');await flushPromises();
  await wrapper.findAll('[data-workspace-tab]')[2]!.trigger('click');await flushPromises();
  expect((wrapper.get(summary).element as HTMLInputElement).value).toBe('Unsaved source comparison');
  wrapper.unmount();
});

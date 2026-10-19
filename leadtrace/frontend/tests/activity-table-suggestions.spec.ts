import {flushPromises,mount} from '@vue/test-utils';
import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import ActivityComparison from '../src/review/paper/ActivityComparison.vue';
import {tableStorageKey} from '../src/review/paper/activityTableBuilder';
import {activities,compounds,ids,installReviewer,response,workspace} from './paper-science-v2-fixtures';
const props=()=>({workspace:workspace() as any,active:true});
function install(){const fetcher=vi.fn(async(input:RequestInfo|URL)=>String(input).endsWith('/evidence')?response({workspace_id:ids.workspace,workspace_version:1,items:[],total:0}):String(input).endsWith('/activity-tables')?response({workspace_id:ids.workspace,workspace_version:1,tables:[],other_activity_ids:activities.map(a=>a.id)}):response({workspace_id:ids.workspace,workspace_version:1,compounds,activities}));vi.stubGlobal('fetch',fetcher);return fetcher;}
beforeEach(()=>{installReviewer();localStorage.clear();});afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});
it('shows all unassigned observations in Other with no automatic persistence or guessed source labels',async()=>{
 const fetcher=install();const w=mount(ActivityComparison,{props:props()});await flushPromises();
 expect(w.get('[data-saved-table]').element).toHaveProperty('value','other');expect(w.findAll('[data-comparison-activity]')).toHaveLength(activities.length);
 expect(w.find('[data-generate-tables]').exists()).toBe(false);expect(localStorage.length).toBe(0);expect(fetcher.mock.calls.every(c=>c.length===1||!(c as any)[1]?.method)).toBe(true);w.unmount();
});
it('copies Other into an editable custom draft without automatic source identity or writes',async()=>{
 install();const w=mount(ActivityComparison,{props:props()});await flushPromises();await w.get('[data-table-from-other]').trigger('click');
 expect(w.get('[data-table-kind]').element).toHaveProperty('value','custom');expect(w.get('[data-source-label]').element).toHaveProperty('value','');expect(w.findAll('[data-comparison-activity]')).toHaveLength(activities.length);w.unmount();
});
it('retains malformed browser settings and displays the error without overwriting server tables',async()=>{
 install();const key=tableStorageKey('reviewer',ids.workspace);localStorage.setItem(key,'{broken');const w=mount(ActivityComparison,{props:props()});await flushPromises();
 expect(localStorage.getItem(key)).toBe('{broken');expect(w.find('[data-import-local-tables]').exists()).toBe(false);expect(w.findAll('[data-comparison-activity]')).toHaveLength(activities.length);w.unmount();
});

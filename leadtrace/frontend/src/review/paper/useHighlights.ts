import { inject, provide, ref, watch, type InjectionKey } from 'vue';
import { listHighlights, type Highlight } from '../../v2/highlights';
import { listEvidence } from "../../v2/api";
import type { Evidence, PaperWorkspace } from '../../v2/types';
function createHighlights(workspace:()=>PaperWorkspace|undefined) {
  const evidence=ref<Evidence[]>([]);
  const items=ref<Highlight[]>([]),error=ref(''),loading=ref(false),version=ref(0);
  let generation=0;
  async function refresh() {
    const ws=workspace(),request=++generation;if(!ws)return;
    loading.value=true;error.value='';
    try {const result=await listHighlights(ws.id);if(request!==generation)return;items.value=result.items;version.value=result.workspace_version;
      if(result.items.length){const source=await listEvidence(ws.id);if(request!==generation)return;evidence.value=source.items;}else evidence.value=[];}
    catch {if(request===generation){items.value=[];error.value='文章标注读取失败，请重试。';}}
    finally {if(request===generation)loading.value=false;}
  }
  watch(()=>[workspace()?.id,workspace()?.version],()=>{void refresh();},{immediate:true});
  return {items,evidence,error,loading,version,refresh};
}
type HighlightState=ReturnType<typeof createHighlights>;
const key:InjectionKey<HighlightState>=Symbol('compound-highlights');
export function provideHighlights(workspace:()=>PaperWorkspace|undefined) {const state=createHighlights(workspace);provide(key,state);return state;}
export const useHighlights=()=>inject(key,undefined);

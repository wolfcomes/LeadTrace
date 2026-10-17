<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from 'vue';
import { z } from 'zod';
import { apiRequest, ApiError } from '../../api/client';
import { useAuthStore } from '../../auth/store';
import { locale } from '../../i18n';
const props=defineProps<{workspaceId:string;version:number;readOnly?:boolean;blocked?:boolean}>();
const emit=defineEmits<{restored:[];conflict:[];busy:[value:boolean]}>();
const auth=useAuthStore();
const schema=z.object({workspace_version:z.number().int().positive(),undo_action:z.string().nullable(),redo_action:z.string().nullable()});
const state=ref<z.infer<typeof schema>>();
const loading=ref(false),busy=ref(false),error=ref('');
let generation=0;
const text=(zh:string,en:string)=>locale.value==='en'?en:zh;
function label(action:string|null|undefined){
 if(!action)return '';
 const [kind,operation]=action.split('.');
 const kinds:Record<string,string>={compound:'Compound',lineage:'Lineage',lineage_member:'Member',lineage_edge:'Edge',structure:'Structure',activity:'Activity',evidence:'Evidence',bibliography:text('文章信息','Article information'),section:text('区段状态','Section status')};
 const operations:Record<string,string>={create:text('新增','Create'),update:text('修改','Update'),delete:text('删除','Delete'),paste:text('粘贴','Paste'),reorder:text('排序','Reorder')};
 return `${operations[operation??'']??operation} ${kinds[kind??'']??kind}`;
}
async function load(){
 const epoch=++generation,id=props.workspaceId;loading.value=true;
 try{const result=await apiRequest(`/api/v2/workspaces/${id}/edit-history`,schema);if(epoch===generation){state.value=result;error.value='';}}
 catch{if(epoch===generation){state.value=undefined;error.value=text('操作历史暂时无法读取。','Edit history is unavailable.');}}
 finally{if(epoch===generation)loading.value=false;}
}
async function move(direction:'undo'|'redo'){
 if(props.readOnly||props.blocked||busy.value||loading.value||state.value?.workspace_version!==props.version)return;
 const id=props.workspaceId,epoch=generation;busy.value=true;emit('busy',true);error.value='';
 try{const result=await apiRequest(`/api/v2/workspaces/${id}/edit-history/${direction}`,schema,{method:'POST',csrfToken:auth.csrfToken,body:{expected_workspace_version:props.version}});if(epoch===generation){state.value=result;emit('restored');}}
 catch(reason){if(epoch===generation){error.value=text('操作未完成；内容可能已更新，请重新载入后重试。','The edit was not restored. Reload the current content and retry.');if(reason instanceof ApiError&&reason.status===409)emit('conflict');}}
 finally{busy.value=false;emit('busy',false);}
}
watch(()=>[props.workspaceId,props.version],()=>void load(),{immediate:true});
onBeforeUnmount(()=>{generation++;});
</script>
<template>
 <div class="workspace-history" data-workspace-history>
  <div class="editor-actions">
   <button type="button" class="button-secondary" data-undo :disabled="readOnly||blocked||busy||loading||!state?.undo_action||state.workspace_version!==version" @click="move('undo')">↶ {{ text('撤销','Undo') }}<span v-if="state?.undo_action"> · {{ label(state.undo_action) }}</span></button>
   <button type="button" class="button-secondary" data-redo :disabled="readOnly||blocked||busy||loading||!state?.redo_action||state.workspace_version!==version" @click="move('redo')">↷ {{ text('重做','Redo') }}<span v-if="state?.redo_action"> · {{ label(state.redo_action) }}</span></button>
  </div>
  <p v-if="blocked" class="inline-feedback is-warning">{{ text('请先保存或取消当前编辑，再撤销或重做。','Save or cancel the current edit before using undo or redo.') }}</p>
  <p v-if="error" role="status">{{ error }} <button type="button" class="button-quiet" :disabled="busy||loading" @click="load">{{ text('刷新','Refresh') }}</button></p>
 </div>
</template>

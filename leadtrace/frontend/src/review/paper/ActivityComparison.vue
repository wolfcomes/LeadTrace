<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { t } from '../../i18n';
import { useAuthStore } from '../../auth/store';
import { getActivityComparison } from '../../v2/api';
import type { ActivityComparison, PaperWorkspace } from '../../v2/types';
import { buildComparisonTable, parseSavedTables, tableSchema, tableStorageKey, type ComparisonColumn, type ComparisonTable, type SavedTables } from './activityTableBuilder';
import ActivityColumnEditor from './ActivityColumnEditor.vue';
import ReviewHint from './ReviewHint.vue';
const props=defineProps<{workspace:PaperWorkspace;active:boolean;blocked?:boolean}>();
const emit=defineEmits<{open:[compoundId:string,activityId?:string]}>();
const auth=useAuthStore();
const data=ref<ActivityComparison>();
const loading=ref(false),error=ref(''),search=ref(''),storageError=ref(''),notice=ref('');
const emptyTable=():ComparisonTable=>({id:crypto.randomUUID(),name:'',columns:[],mode:'any',sort:'label'});
const draft=ref<ComparisonTable>(emptyTable()),saved=ref<ComparisonTable[]>([]),baseline=ref('');
const activeSavedId=ref<string|null>(null),settingsBusy=ref(false);
let settingsEpoch=0;
const editing=ref<ComparisonColumn|null|undefined>(undefined),editorEpoch=ref(0),showConfiguration=ref(true);
const pending=ref<{kind:'new'|'switch'|'delete';id?:string}>();
const dragId=ref<string>();
const viewport=ref<HTMLElement>();
let sequence=0,position={top:0,left:0};
const storageKey=computed(()=>tableStorageKey(auth.user?.username??'',props.workspace.id));
const dirty=computed(()=>JSON.stringify(draft.value)!==baseline.value);
const table=computed(()=>buildComparisonTable(data.value?.compounds??[],data.value?.activities??[],draft.value.columns,draft.value.mode,draft.value.sort));
const compounds=computed(()=>{const query=search.value.trim().toLocaleLowerCase();return table.value.rows.filter(c=>`${c.compound_label} ${c.display_name??''}`.toLocaleLowerCase().includes(query));});
const savedOptions=computed(()=>saved.value);
const copy=<T,>(value:T):T=>JSON.parse(JSON.stringify(value));
function setDraft(value:ComparisonTable,id:string|null){draft.value=copy(value);activeSavedId.value=id;baseline.value=JSON.stringify(draft.value);editing.value=undefined;pending.value=undefined;notice.value='';}
function readSettings(){
 storageError.value='';saved.value=[];setDraft(emptyTable(),null);
 try {
  const raw=window.localStorage.getItem(storageKey.value),parsed=parseSavedTables(raw);
  if(raw&&!parsed){storageError.value='已有表格配置无法读取，为避免覆盖暂不保存；仍可临时制表。';return;}
  if(parsed){saved.value=parsed.tables;const selected=parsed.tables.find(t=>t.id===parsed.activeId);if(selected)setDraft(selected,selected.id);}
 }catch{storageError.value='无法读取浏览器中的表格配置，当前仍可制表。';}
}
function latestSettings():SavedTables {
 const raw=window.localStorage.getItem(storageKey.value);
 const parsed=parseSavedTables(raw);
 if(raw&&!parsed)throw Error('已有表格配置无法读取，为避免覆盖暂不保存；仍可临时制表。');
 return parsed??{version:1,activeId:null,tables:[]};
}
function writeSettings(tables:ComparisonTable[],activeId:string|null){
 const record:SavedTables={version:1,activeId,tables};
 window.localStorage.setItem(storageKey.value,JSON.stringify(record));
 saved.value=tables;storageError.value='';
}
function checkUnchanged(tables:ComparisonTable[],id:string){
 if(JSON.stringify(tables.find(t=>t.id===id))!==JSON.stringify(saved.value.find(t=>t.id===id)))
  throw Error('此表格已被其他标签页修改或删除。当前设置仍保留；请重新选择已保存表格后再修改。');
}
async function changeSettings(change:()=>void){
 if(settingsBusy.value)return;
 const key=storageKey.value,epoch=settingsEpoch;
 settingsBusy.value=true;
 const run=()=>{
  if(key!==storageKey.value||epoch!==settingsEpoch)return;
  try{change();}
  catch(e){storageError.value=e instanceof Error&&[
   '已有同名表格，请使用其他名称。','已达到保存表格数量上限，请先删除不需要的表格。',
   '已有表格配置无法读取，为避免覆盖暂不保存；仍可临时制表。',
   '此表格已被其他标签页修改或删除。当前设置仍保留；请重新选择已保存表格后再修改。',
  ].includes(e.message)?e.message:'未能保存到此浏览器；当前表格仍保留，请重试。';}
 };
 try{
  // Serialize read/merge/write across tabs when the browser provides Web Locks.
  if(navigator.locks)await navigator.locks.request(key,run);else run();
 }catch{if(epoch===settingsEpoch)storageError.value='未能保存到此浏览器；当前表格仍保留，请重试。';}
 finally{if(epoch===settingsEpoch)settingsBusy.value=false;}
}
function saveTable(){
 const parsed=tableSchema.safeParse(draft.value);
 if(!parsed.success){storageError.value='请填写表格名称，并检查列配置。';return;}
 void changeSettings(()=>{
  const latest=latestSettings();checkUnchanged(latest.tables,parsed.data.id);
  if(latest.tables.some(t=>t.id!==parsed.data.id&&t.name===parsed.data.name))throw Error('已有同名表格，请使用其他名称。');
  const tables=latest.tables.filter(t=>t.id!==parsed.data.id).concat(parsed.data);
  if(tables.length>50)throw Error('已达到保存表格数量上限，请先删除不需要的表格。');
  writeSettings(tables,parsed.data.id);
  draft.value=parsed.data;activeSavedId.value=parsed.data.id;baseline.value=JSON.stringify(draft.value);pending.value=undefined;notice.value='表格配置已保存在此浏览器。';
 });
}
function perform(action:NonNullable<typeof pending.value>){
 const resetPosition=()=>{search.value='';position={top:0,left:0};void restoreScroll();};
 if(action.kind==='new'){setDraft(emptyTable(),null);resetPosition();return;}
 void changeSettings(()=>{
  const latest=latestSettings();
  if(action.kind==='switch'){
   const target=latest.tables.find(t=>t.id===action.id);
   if(!target)throw Error('此表格已被其他标签页修改或删除。当前设置仍保留；请重新选择已保存表格后再修改。');
   writeSettings(latest.tables,target.id);setDraft(target,target.id);
  }else{
   checkUnchanged(latest.tables,activeSavedId.value!);
   const remaining=latest.tables.filter(t=>t.id!==activeSavedId.value);
   writeSettings(remaining,remaining[0]?.id??null);
   setDraft(remaining[0]??emptyTable(),remaining[0]?.id??null);
  }
  resetPosition();
 });
}
function request(action:NonNullable<typeof pending.value>){
 if(editing.value!==undefined)return;
 if(dirty.value||action.kind==='delete')pending.value=action;else perform(action);
}
function beginColumn(column:ComparisonColumn|null){editing.value=column?copy(column):null;editorEpoch.value++;showConfiguration.value=true;notice.value='';}
function applyColumn(column:ComparisonColumn){
 const index=draft.value.columns.findIndex(c=>c.id===column.id);
 if(index<0)draft.value.columns.push(column);else draft.value.columns.splice(index,1,column);
 editing.value=undefined;
}
function moveColumn(id:string,target:number){
 const from=draft.value.columns.findIndex(c=>c.id===id);
 if(from<0||target<0||target>=draft.value.columns.length)return;
 const [column]=draft.value.columns.splice(from,1);if(column)draft.value.columns.splice(target,0,column);
}
function dropColumn(index:number){if(dragId.value)moveColumn(dragId.value,index);dragId.value=undefined;}
function missingRecords(column:ComparisonColumn){return column.activityIds===null?0:column.activityIds.filter(id=>!table.value.matches.get(column.id)?.some(a=>a.id===id)).length;}
function rememberScroll(){if(props.active&&!loading.value&&viewport.value)position={top:viewport.value.scrollTop,left:viewport.value.scrollLeft};}
async function restoreScroll(){await nextTick();if(props.active&&viewport.value){viewport.value.scrollTop=position.top;viewport.value.scrollLeft=position.left;}}
async function load(){
 const epoch=++sequence,id=props.workspace.id;loading.value=true;error.value='';
 try{const result=await getActivityComparison(id);if(epoch!==sequence||id!==props.workspace.id)return;
  if(result.workspace_id!==id||result.workspace_version<props.workspace.version)throw Error('Stale comparison');data.value=result;
 }catch{if(epoch===sequence)error.value='活性对比暂时无法读取，请重试。';}
 finally{if(epoch===sequence){loading.value=false;await restoreScroll();}}
}
function open(compoundId:string,activityId?:string){
 if(props.blocked||loading.value||error.value||!props.active)return;
 rememberScroll();if(activityId)emit('open',compoundId,activityId);else emit('open',compoundId);
}
watch([()=>props.workspace.id,()=>auth.user?.username],()=>{settingsEpoch++;settingsBusy.value=false;sequence++;data.value=undefined;search.value='';position={top:0,left:0};readSettings();},{immediate:true});
watch(()=>[props.workspace.id,props.active,props.workspace.version,auth.user?.username] as const,([id,active],previous)=>{
 if(active&&(!previous?.[1]||id!==previous[0]||data.value?.workspace_version!==props.workspace.version))void load();
},{immediate:true});
onBeforeUnmount(()=>{settingsEpoch++;sequence++;});
</script>

<template>
 <section class="activity-comparison" data-activity-comparison>
  <header class="comparison-heading"><div><h2>{{t('活性对比')}}</h2><p>{{t('选择测定列，自动展示有相关数据的 Compound。')}}</p></div><button type="button" class="button-secondary" :disabled="loading" data-comparison-refresh @click="load">{{t('刷新')}}</button></header>
  <div :inert="settingsBusy" :aria-busy="settingsBusy">
  <div class="comparison-toolbar saved-toolbar">
   <label class="form-field">{{t('已保存的表格')}}<select data-saved-table :value="activeSavedId??''" :disabled="editing!==undefined" @change="request({kind:'switch',id:($event.target as HTMLSelectElement).value})"><option value="" disabled>{{t('未保存的表格')}}</option><option v-for="item in savedOptions" :key="item.id" :value="item.id">{{item.name}}</option></select></label>
   <label class="form-field">{{t('表格名称')}}<input v-model="draft.name" data-table-name maxlength="120" :placeholder="t('例如：主要活性')"></label>
   <div class="editor-actions"><button type="button" class="button-secondary" data-save-table :disabled="editing!==undefined" @click="saveTable">{{t('保存表格')}}</button><button type="button" class="button-quiet" data-new-table :disabled="editing!==undefined" @click="request({kind:'new'})">{{t('新建表格')}}</button><button v-if="activeSavedId" type="button" class="button-quiet" data-delete-table :disabled="editing!==undefined" @click="request({kind:'delete'})">{{t('删除表格')}}</button></div>
  </div>
  <p class="settings-note">{{t('配置仅保存在此浏览器，按账号和文章区分；数据始终读取最新保存记录。')}} <strong v-if="dirty">{{t('表格设置尚未保存。')}}</strong></p>
  <p v-if="notice" role="status">{{t(notice)}}</p><p v-if="storageError" role="alert" data-table-storage-error>{{t(storageError)}}</p>
  <div v-if="pending" class="pending-settings" role="alert"><p>{{t(pending.kind==='delete'?'删除这张已保存的表格配置？科学记录不会删除。':'当前表格设置尚未保存，是否放弃设置并继续？')}}</p><button type="button" class="button-secondary" data-discard-table-changes @click="perform(pending!)">{{t(pending.kind==='delete'?'删除表格':'放弃设置并继续')}}</button><button type="button" class="button-quiet" @click="pending=undefined">{{t('取消')}}</button></div>
  <div class="comparison-toolbar">
   <label class="form-field">{{t('搜索编号或名称')}}<input v-model="search" data-comparison-search type="search" :placeholder="t('搜索编号或名称')"></label>
   <label class="form-field">{{t('显示范围')}}<select v-model="draft.mode" data-comparison-row-mode><option value="any">{{t('至少一列有记录')}}</option><option value="all">{{t('每列都有记录')}}</option></select></label>
   <label class="form-field">{{t('排序方式')}}<select v-model="draft.sort" data-comparison-sort><option value="label">{{t('名称排序')}}</option><option value="similarity">{{t('相似测定组合')}}</option><option value="default">{{t('默认排序')}}</option></select></label>
  </div>
  <div class="column-controls"><button type="button" class="button-primary" data-add-column :disabled="loading||!!error||!data?.activities.length||editing!==undefined||draft.columns.length>=60" @click="beginColumn(null)">{{t('添加列')}}</button><button v-if="draft.columns.length" type="button" class="button-quiet" data-toggle-column-config :aria-expanded="showConfiguration" @click="showConfiguration=!showConfiguration">{{t(showConfiguration?'收起列配置':'配置列')}} ({{draft.columns.length}})</button></div>
  <div v-if="showConfiguration&&draft.columns.length" class="configured-columns" data-configured-columns :inert="editing!==undefined">
   <div v-for="(column,index) in draft.columns" :key="column.id" class="configured-column" data-configured-column draggable="true" @dragstart="dragId=column.id; $event.dataTransfer?.setData('text/plain',column.id)" @dragend="dragId=undefined" @dragover.prevent @drop.prevent="dropColumn(index)">
    <div><strong>{{index+1}}. {{column.label}}</strong><small>{{column.assay}} · {{column.metric}} · {{column.unit||t('未记录单位')}}</small><small>{{t(column.activityIds===null?'全部记录（包含后续新增）':'仅选中记录')}} · {{table.matches.get(column.id)?.length??0}} {{t('条记录')}}</small></div>
    <div class="editor-actions"><button type="button" class="button-quiet" data-column-edit @click="beginColumn(column)">{{t('编辑列')}}</button><button type="button" class="button-quiet" data-column-move-left :disabled="index===0" :aria-label="t('左移列：{name}',{name:column.label})" @click="moveColumn(column.id,index-1)">←</button><button type="button" class="button-quiet" data-column-move-right :disabled="index===draft.columns.length-1" :aria-label="t('右移列：{name}',{name:column.label})" @click="moveColumn(column.id,index+1)">→</button><button type="button" class="button-quiet" data-column-remove @click="draft.columns.splice(index,1)">{{t('移除')}}</button></div>
   </div>
  </div>
  <div :inert="loading"><ActivityColumnEditor v-if="editing!==undefined&&data" :key="editorEpoch" :activities="data.activities" :compounds="data.compounds" :columns="draft.columns" :column="editing" @apply="applyColumn" @cancel="editing=undefined" /></div>
  <p v-if="blocked" class="inline-feedback is-warning">{{t('请先保存或取消当前编辑，再打开其他条目。')}}</p>
  <p v-if="loading" role="status">{{t('正在读取活性对比…')}}</p>
  <p v-if="error" role="alert">{{t(error)}} <button type="button" class="button-quiet" data-comparison-retry @click="load">{{t('重试')}}</button></p>
  <template v-if="data&&!error">
   <p v-if="!data.activities.length&&!loading">{{t('当前文章尚无活性记录。')}}</p>
   <p v-else-if="!draft.columns.length&&!loading" data-comparison-empty>{{t('点击“添加列”，选择要比较的测定和记录。')}}</p>
   <template v-else-if="!loading">
    <p v-for="column in draft.columns.filter(c=>missingRecords(c)>0)" :key="column.id" class="inline-feedback is-warning" data-column-stale>{{t('列“{name}”有 {count} 条所选记录已删除或测定发生变化，请检查列设置。',{name:column.label,count:missingRecords(column)})}}</p>
    <p v-if="!compounds.length">{{t('没有符合当前列配置和显示范围的 Compound。')}}</p>
    <p class="comparison-coverage">{{t('显示 {shown}/{total} 个 Compound',{shown:compounds.length,total:data.compounds.length})}}</p>
   </template>
   <div v-show="!loading&&compounds.length>0" ref="viewport" class="comparison-scroll" data-comparison-scroll tabindex="0" role="region" :aria-label="t('Compound 活性对比表')" @scroll="rememberScroll">
    <table class="comparison-grid">
     <caption>{{t('— 表示无对应记录；条件与单位保留，同格多条记录全部列出。')}}</caption>
     <thead><tr><th scope="col" class="compound-column">Compound</th><th v-for="column in draft.columns" :key="column.id" scope="col" data-comparison-column><span class="measurement-assay">{{column.label}}</span><small>{{column.metric}} · {{column.unit||t('未记录单位')}}</small><details class="measurement-context"><summary>{{t('关联测定')}}</summary><p>{{column.assay}}</p></details></th></tr></thead>
     <tbody><tr v-for="compound in compounds" :key="compound.id" data-comparison-row :data-compound-id="compound.id">
      <th scope="row" class="compound-column"><button type="button" class="comparison-link" data-comparison-compound :disabled="blocked||loading" @click="open(compound.id)">{{compound.compound_label}}</button><details v-if="compound.display_name" class="compound-name"><summary :title="compound.display_name">{{t('名称')}}</summary><small>{{compound.display_name}}</small></details><ReviewHint :hint="compound.review_hint" /></th>
      <td v-for="column in draft.columns" :key="column.id"><template v-if="table.cells.get(compound.id)?.get(column.id)?.length"><div v-for="activity in table.cells.get(compound.id)?.get(column.id)" :key="activity.id" class="measurement-value"><button type="button" class="comparison-link" data-comparison-activity :data-activity-id="activity.id" :disabled="blocked||loading" :aria-label="t('查看 {compound} 的活性记录：{value}',{compound:compound.compound_label,value:`${activity.operator} ${activity.value} ${activity.unit??''}`})" @click="open(compound.id,activity.id)">{{activity.operator}} {{activity.value}}</button><ReviewHint :hint="activity.review_hint" /><details class="measurement-context record-context" data-measurement-context><summary :title="activity.context||t('未记录实验条件')">{{activity.context||t('未记录实验条件')}}</summary><p>{{activity.context||t('未记录实验条件')}}</p></details></div></template><span v-else class="missing-measurement">—</span></td>
     </tr></tbody>
    </table>
   </div>
  </template>
  </div>
 </section>
</template>
<style scoped>
.activity-comparison { min-width: 0; }
.comparison-heading, .comparison-toolbar { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; }
.comparison-heading h2 { margin: 0; }
.comparison-heading p { color: var(--muted); font-size: .82rem; }
.comparison-toolbar { justify-content: flex-start; margin: 16px 0; align-items: flex-end; }
.comparison-toolbar .form-field { min-width: 150px; }
.comparison-toolbar .comparison-group-select { flex: 1 1 260px; min-width: 0; }
.comparison-group-select select { width: 100%; text-overflow: ellipsis; }
.comparison-options, .comparison-coverage { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin: 12px 0; }
.comparison-coverage { justify-content: space-between; color: var(--muted); font-size: .75rem; }
.comparison-coverage label { display: flex; align-items: center; gap: 6px; }
.comparison-coverage input { width: auto; min-height: auto; }
.measurement-options fieldset { border: 0; padding: 10px 0; margin: 0; min-width: 0; }
.measurement-options legend { font-weight: 600; overflow-wrap: anywhere; }
.measurement-assay { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.compound-name { display: inline-block; margin-left: 6px; font-size: .7rem; font-weight: normal; }
.compound-name summary { cursor: pointer; color: var(--muted); }
.measurement-picker { position: relative; max-width: 100%; padding: 10px; border: 1px solid var(--line); border-radius: 6px; }
.measurement-picker summary { cursor: pointer; }
.measurement-options { max-height: 300px; max-width: min(600px, 80vw); overflow: auto; }
.measurement-options label { display: flex; align-items: flex-start; gap: 8px; padding: 8px 0; overflow-wrap: anywhere; }
.measurement-options input { flex: 0 0 auto; width: auto; min-height: auto; margin-top: 4px; }
small { display: block; font-weight: normal; font-size: .75rem; color: var(--muted); overflow-wrap: anywhere; }
.comparison-scroll { max-height: 65vh; overflow: auto; border: 1px solid var(--line); border-radius: 6px; }
.comparison-grid { border-collapse: separate; border-spacing: 0; width: max-content; min-width: min(100%, 480px); font-size: .85rem; }
caption { caption-side: bottom; text-align: left; padding: 12px; color: var(--muted); font-size: .75rem; }
th, td { padding: 8px 10px; border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; min-width: 150px; max-width: 210px; overflow-wrap: anywhere; }
thead th { position: sticky; top: 0; background: var(--paper); z-index: 2; }
.compound-column { position: sticky; left: 0; background: var(--paper); z-index: 1; min-width: 100px; max-width: 140px; }
thead .compound-column { z-index: 3; }
.measurement-context { font-size: .75rem; font-weight: normal; margin-top: 6px; }
.measurement-context summary { cursor: pointer; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.measurement-context p { white-space: pre-wrap; }
.record-context { flex-basis: 100%; min-width: 0; }
.measurement-value { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px; margin-bottom: 4px; }
.comparison-link { border: 0; background: transparent; padding: 2px 0; color: var(--teal); text-decoration: underline; text-underline-offset: 3px; cursor: pointer; text-align: left; font: inherit; font-variant-numeric: tabular-nums; }
.comparison-link:disabled { cursor: default; opacity: .55; }
.missing-measurement { color: var(--muted); }
@media (max-width: 600px) { .comparison-toolbar .form-field { flex: 1 1 140px; } th, td { min-width: 140px; } .compound-column { min-width: 85px; max-width: 110px; } }
.column-controls { display: flex; gap: 12px; align-items: center; margin: 12px 0; }
.configured-columns { display: flex; flex-wrap: wrap; gap: 10px; margin: 12px 0; }
.configured-column { flex: 1 1 240px; max-width: 400px; min-width: 0; padding: 10px; border: 1px solid var(--line); border-radius: 4px; overflow-wrap: anywhere; }
.configured-column .editor-actions { margin-top: 6px; }
.settings-note { color: var(--muted); font-size: .75rem; }
.pending-settings { border: 1px solid var(--line); padding: 12px; }
.saved-toolbar .form-field { flex: 1 1 180px; min-width: 0; }
.saved-toolbar input, .saved-toolbar select { width: 100%; }
</style>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { t } from '../../i18n';
import { useAuthStore } from '../../auth/store';
import { ApiError } from '../../api/client';
import { getActivityComparison, getActivityTables, saveActivityTable, deleteActivityTable, confirmActivityTable, listEvidence } from '../../v2/api';
import type { ActivityComparison, ActivityTable, ActivityTableWrite, Evidence, PaperWorkspace } from '../../v2/types';
import { buildComparisonTable, matchingActivities, recommendMeasurements, parseSavedTables, tableSchema, tableStorageKey, type ComparisonColumn, type ComparisonTable } from './activityTableBuilder';
import ActivityColumnEditor from './ActivityColumnEditor.vue';
import TableEvidenceImages from './TableEvidenceImages.vue';
import EvidenceEditor from './EvidenceEditor.vue';
import { validateCrop } from '../../approvals/frozenPdf';
import ReviewHint from './ReviewHint.vue';
const props=defineProps<{workspace:PaperWorkspace;active:boolean;blocked?:boolean;readOnly?:boolean;selectedTableId?:string}>();
const emit=defineEmits<{open:[compoundId:string,activityId?:string];mutated:[];busy:[value:boolean]}>();
const auth=useAuthStore();
type Draft=ComparisonTable & Pick<ActivityTable,'kind'|'source_label'|'source_title'|'page_number'|'review_hint'> & {compound_ids:string[]|null;evidence_ids:string[]};
const emptyTable=():Draft=>({id:crypto.randomUUID(),name:'',compound_ids:null,evidence_ids:[],columns:[],mode:'any',sort:'label',kind:'custom',source_label:null,source_title:null,page_number:null,review_hint:null});
const data=ref<ActivityComparison>(),saved=ref<ActivityTable[]>([]),legacy=ref<ComparisonTable[]>([]);
const evidence=ref<Evidence[]>([]),showRows=ref(false),addRowId=ref(''),rowSearch=ref(''),showEvidenceEditor=ref(false);
const legacyError=ref('');
const loading=ref(false),error=ref(''),search=ref(''),storageError=ref(''),notice=ref(''),settingsBusy=ref(false);
const draft=ref<Draft>(emptyTable()),baseline=ref(''),activeSavedId=ref<string|null>('other'),loadedVersion=ref(0),draftVersion=ref(0);
const legacyIds=new Map<string,string>();
const otherIds=ref<string[]>([]),initialized=ref(false);
const editing=ref<ComparisonColumn|null|undefined>(undefined),editorEpoch=ref(0),showConfiguration=ref(false);
const pending=ref<{kind:'new'|'switch'|'delete'|'from-other';id?:string}>();
const dragId=ref<string>(),viewport=ref<HTMLElement>();
let sequence=0,mutationEpoch=0,position={top:0,left:0};
const isOther=computed(()=>activeSavedId.value==='other');
const editable=computed(()=>!props.readOnly&&auth.user?.role==='reviewer'&&props.workspace.state==='editing');
const mayMutate=computed(()=>editable.value&&!props.blocked&&!loading.value&&!error.value&&!settingsBusy.value&&!showEvidenceEditor.value);
const dirty=computed(()=>editable.value&&!isOther.value&&JSON.stringify(draft.value)!==baseline.value);
const activeSaved=computed(()=>saved.value.find(item=>item.id===activeSavedId.value));
const otherColumns=computed(()=>{
 const ids=new Set(otherIds.value),records=(data.value?.activities??[]).filter(a=>ids.has(a.id));
 return recommendMeasurements(records,[]).map(group=>({id:group.key,label:`${group.assay} · ${group.metric}`,assay:group.assay,metric:group.metric,unit:group.unit,activityIds:records.filter(a=>a.assay_name===group.assay&&a.metric===group.metric&&a.unit===group.unit).map(a=>a.id)}));
});
const columns=computed(()=>isOther.value?otherColumns.value:draft.value.columns);
const table=computed(()=>buildComparisonTable(data.value?.compounds??[],data.value?.activities??[],columns.value,draft.value.mode,draft.value.sort,isOther.value?null:draft.value.compound_ids));
const compounds=computed(()=>{const query=search.value.trim().toLocaleLowerCase();return table.value.rows.filter(c=>`${c.compound_label} ${c.display_name??''}`.toLocaleLowerCase().includes(query));});
const copy=<T,>(value:T):T=>JSON.parse(JSON.stringify(value));
function fromServer(item:ActivityTable):Draft{return {...emptyTable(),id:item.id,name:item.name,kind:item.kind,source_label:item.source_label,source_title:item.source_title,page_number:item.page_number,review_hint:item.review_hint,compound_ids:item.compound_ids??null,evidence_ids:item.evidence_ids??[],mode:item.mode,sort:item.sort,columns:item.columns.map(c=>({id:c.id,label:c.label,assay:c.assay,metric:c.metric,unit:c.unit,activityIds:c.activity_ids}))};}
const orderedSaved=computed(()=>[...saved.value].sort((a,b)=>a.kind!==b.kind?(a.kind==='source'?-1:1):a.kind==='source'?(a.source_label??a.name).localeCompare(b.source_label??b.name,'en',{numeric:true,sensitivity:'base'}):0));
const savedOptions=computed(()=>orderedSaved.value.map(item=>({...item,compoundCount:buildComparisonTable(data.value?.compounds??[],data.value?.activities??[],fromServer(item).columns,item.mode,'default',item.compound_ids).rows.length})));
function setDraft(value:Draft,id:string|null){draft.value=copy(value);activeSavedId.value=id;draftVersion.value=loadedVersion.value;baseline.value=JSON.stringify(draft.value);editing.value=undefined;rowSearch.value='';addRowId.value='';showEvidenceEditor.value=false;pending.value=undefined;notice.value='';storageError.value='';}
function select(id:string){const item=saved.value.find(t=>t.id===id),view=isOther.value?{mode:draft.value.mode,sort:draft.value.sort}:{};setDraft(item?fromServer(item):{...emptyTable(),name:'Other',...view},item?.id??'other');}
function readLegacy(){legacy.value=[];legacyError.value='';try{const raw=localStorage.getItem(tableStorageKey(auth.user?.username??'',props.workspace.id)),parsed=parseSavedTables(raw);if(raw&&!parsed)legacyError.value='浏览器中的旧表格无法读取，原配置已保留。';else legacy.value=parsed?.tables??[];}catch{legacyError.value='浏览器中的旧表格无法读取，原配置已保留。';}}
function payload(value:Draft):ActivityTableWrite{
 const parsed=tableSchema.safeParse({id:value.id,name:value.name,columns:value.columns,mode:value.mode,sort:value.sort});
 if(!parsed.success||value.kind==='source'&&!value.source_label?.trim())throw Error('请填写表格名称、原文表号，并检查列配置。');
 return {compound_ids:value.compound_ids,evidence_ids:value.evidence_ids,name:parsed.data.name,kind:value.kind,source_label:value.source_label?.trim()||null,source_title:value.source_title?.trim()||null,page_number:value.page_number?Number(value.page_number):null,review_hint:value.review_hint,mode:value.mode,sort:value.sort,columns:value.columns.map(c=>({id:c.id,label:c.label,assay:c.assay,metric:c.metric,unit:c.unit,activity_ids:c.activityIds??matchingActivities(c,data.value?.activities??[]).map(a=>a.id)}))};
}
function recomputeOther(){const assigned=new Set(saved.value.flatMap(t=>t.columns.flatMap(c=>c.activity_ids)));otherIds.value=(data.value?.activities??[]).filter(a=>!assigned.has(a.id)).map(a=>a.id);}
async function mutate(operation:(id:string,version:number,current:()=>boolean)=>Promise<void>){
 if(!mayMutate.value)return;const epoch=mutationEpoch,id=props.workspace.id,initialVersion=loadedVersion.value;settingsBusy.value=true;storageError.value='';
 try{await operation(id,draftVersion.value,()=>epoch===mutationEpoch&&id===props.workspace.id);if(epoch!==mutationEpoch||id!==props.workspace.id)return;recomputeOther();}
 catch(e){if(epoch!==mutationEpoch)return;storageError.value=e instanceof ApiError&&e.status===409?'工作区版本已变化。当前设置已保留，请刷新并重新选择已保存表格后再修改。':e instanceof Error&&e.message==='请填写表格名称、原文表号，并检查列配置。'?e.message:'表格未能保存，请重试；当前设置与浏览器旧配置均已保留。';}
 finally{if(epoch===mutationEpoch){if(loadedVersion.value!==initialVersion){recomputeOther();emit('mutated');}settingsBusy.value=false;}}
}
function accept(item:ActivityTable,version:number){saved.value=saved.value.filter(t=>t.id!==item.id).concat(item);loadedVersion.value=version;setDraft(fromServer(item),item.id);}
function saveTable(){if(isOther.value||editing.value!==undefined)return;void mutate(async(id,version,current)=>{const result=await saveActivityTable(id,draft.value.id,payload(draft.value),version,auth.csrfToken);if(!current())return;accept(result.table,result.workspace_version);notice.value='表格已保存到文章工作区。';});}
function confirmTable(status:'reviewer_confirmed'|'unresolved'='reviewer_confirmed'){if(!activeSaved.value||dirty.value||editing.value!==undefined)return;void mutate(async(id,version,current)=>{const result=await confirmActivityTable(id,activeSavedId.value!,version,auth.csrfToken,status);if(!current())return;accept(result.table,result.workspace_version);notice.value=status==='reviewer_confirmed'?'表格已确认。':'表格无法判定。';});}
async function importLegacy(){
 if(!mayMutate.value)return;
 // The browser copy remains intact, including after partial failures. Reuse valid IDs so retries are idempotent.
 await mutate(async(id,_version,current)=>{let version=loadedVersion.value;for(const old of legacy.value){
  const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(old.id)?old.id:(legacyIds.get(old.id)??crypto.randomUUID());legacyIds.set(old.id,uuid);
  if(saved.value.some(item=>item.id===uuid))continue;
  const value={...emptyTable(),...copy(old),id:uuid};const result=await saveActivityTable(id,uuid,payload(value),version,auth.csrfToken);if(!current())return;
  version=result.workspace_version;saved.value.push(result.table);loadedVersion.value=version;
 }select(saved.value[0]?.id??'other');notice.value='浏览器旧表格已导入为自定义表格，原配置仍保留。';});
}
function perform(action:NonNullable<typeof pending.value>){
 if(action.kind==='delete'){
  void mutate(async(id,version,current)=>{const deleted=activeSavedId.value!;const result=await deleteActivityTable(id,deleted,version,auth.csrfToken);if(!current())return;saved.value=saved.value.filter(t=>t.id!==deleted);loadedVersion.value=result.workspace_version;select('other');});return;
 }
 if(action.kind==='new')setDraft(emptyTable(),null);
 else if(action.kind==='from-other')setDraft({...emptyTable(),columns:copy(otherColumns.value)},null);
 else select(action.id??'other');
 showConfiguration.value=action.kind!=='switch';search.value='';position={top:0,left:0};void restoreScroll();
}
function request(action:NonNullable<typeof pending.value>){if(editing.value!==undefined||settingsBusy.value||showEvidenceEditor.value)return;if(dirty.value||action.kind==='delete')pending.value=action;else perform(action);}
function beginColumn(column:ComparisonColumn|null){if(!mayMutate.value||isOther.value)return;editing.value=column?copy(column):null;editorEpoch.value++;showConfiguration.value=true;notice.value='';}
function applyColumn(column:ComparisonColumn){if(!editable.value)return;const records=matchingActivities(column,data.value?.activities??[]);const exact={...column,activityIds:records.map(a=>a.id)};if(draft.value.compound_ids!==null)for(const a of records)if(!draft.value.compound_ids.includes(a.compound_id))draft.value.compound_ids.push(a.compound_id);const index=draft.value.columns.findIndex(c=>c.id===column.id);if(index<0)draft.value.columns.push(exact);else draft.value.columns.splice(index,1,exact);editing.value=undefined;}
function moveColumn(id:string,target:number){const from=draft.value.columns.findIndex(c=>c.id===id);if(from<0||target<0||target>=draft.value.columns.length)return;const [column]=draft.value.columns.splice(from,1);if(column)draft.value.columns.splice(target,0,column);}
function dropColumn(index:number){if(dragId.value)moveColumn(dragId.value,index);dragId.value=undefined;}
const rowIds=computed(()=>draft.value.compound_ids??buildComparisonTable(data.value?.compounds??[],data.value?.activities??[],draft.value.columns,'any','default').rows.map(c=>c.id));
const rowItems=computed(()=>rowIds.value.flatMap(id=>{const c=data.value?.compounds.find(c=>c.id===id);return c?[c]:[];}));
const rowChoices=computed(()=>(data.value?.compounds??[]).filter(c=>!rowIds.value.includes(c.id)&&`${c.compound_label} ${c.display_name??''}`.toLocaleLowerCase().includes(rowSearch.value.trim().toLocaleLowerCase())));
function addRow(){if(!mayMutate.value||!rowChoices.value.some(c=>c.id===addRowId.value))return;draft.value.compound_ids=[...rowIds.value,addRowId.value];draft.value.sort='default';addRowId.value='';}
function removeRow(id:string){if(!mayMutate.value)return;draft.value.compound_ids=rowIds.value.filter(value=>value!==id);for(const col of draft.value.columns)col.activityIds=matchingActivities(col,data.value?.activities??[]).filter(a=>a.compound_id!==id).map(a=>a.id);}
function moveRow(index:number,to:number){if(!mayMutate.value||to<0||to>=rowIds.value.length)return;const ids=[...rowIds.value];const [id]=ids.splice(index,1);ids.splice(to,0,id!);draft.value.compound_ids=ids;draft.value.sort='default';}
const validEvidence=computed(()=>evidence.value.filter(e=>e.kind==='table'&&e.source_sha256===props.workspace.source.sha256&&e.page_number>=1&&e.page_number<=props.workspace.source.page_count&&e.bbox&&validateCrop(e.bbox)));
const invalidLinkedEvidence=computed(()=>draft.value.evidence_ids.filter(id=>!validEvidence.value.some(e=>e.id===id)));
const linkedEvidence=computed(()=>draft.value.evidence_ids.flatMap(id=>evidence.value.filter(e=>e.id===id)));
const missingEvidence=computed(()=>draft.value.kind==='source'&&(!draft.value.evidence_ids.length||draft.value.evidence_ids.some(id=>!validEvidence.value.some(e=>e.id===id))));
async function evidenceMutated(){showEvidenceEditor.value=false;emit('mutated');await load();}
function missingRecords(column:ComparisonColumn){return column.activityIds===null?0:column.activityIds.filter(id=>!table.value.matches.get(column.id)?.some(a=>a.id===id)).length;}
function rememberScroll(){if(props.active&&!loading.value&&viewport.value)position={top:viewport.value.scrollTop,left:viewport.value.scrollLeft};}
async function restoreScroll(){await nextTick();if(props.active&&viewport.value){viewport.value.scrollTop=position.top;viewport.value.scrollLeft=position.left;}}
async function load(){
 const epoch=++sequence,id=props.workspace.id;loading.value=true;error.value='';
 try{const [result,tables,evidenceResult]=await Promise.all([getActivityComparison(id),getActivityTables(id),listEvidence(id)]);if(epoch!==sequence||id!==props.workspace.id)return;
  if(result.workspace_id!==id||tables.workspace_id!==id||result.workspace_version!==tables.workspace_version||evidenceResult.workspace_version!==tables.workspace_version||result.workspace_version<props.workspace.version)throw Error('Stale comparison');
  const keep=dirty.value||editing.value!==undefined||showEvidenceEditor.value;data.value=result;evidence.value=evidenceResult.items;saved.value=tables.tables;otherIds.value=tables.other_activity_ids;loadedVersion.value=tables.workspace_version;
  if(!keep)select(initialized.value?(activeSavedId.value??'other'):(props.selectedTableId??orderedSaved.value[0]?.id??'other'));initialized.value=true;
 }catch{if(epoch===sequence)error.value='活性对比暂时无法读取，请重试。';}
 finally{if(epoch===sequence){loading.value=false;await restoreScroll();}}
}
function open(compoundId:string,activityId?:string){if(props.blocked||dirty.value||editing.value!==undefined||loading.value||settingsBusy.value||error.value||!props.active)return;rememberScroll();if(activityId)emit('open',compoundId,activityId);else emit('open',compoundId);}
watch([()=>props.workspace.id,()=>auth.user?.username],()=>{mutationEpoch++;sequence++;legacyIds.clear();settingsBusy.value=false;data.value=undefined;evidence.value=[];saved.value=[];initialized.value=false;search.value='';position={top:0,left:0};setDraft(emptyTable(),'other');readLegacy();},{immediate:true});
watch(()=>[props.workspace.id,props.active,props.workspace.version,auth.user?.username] as const,([id,active],previous)=>{if(active&&(!previous?.[1]||id!==previous[0]||data.value?.workspace_version!==props.workspace.version))void load();},{immediate:true});
watch(()=>props.selectedTableId,id=>{if(id&&saved.value.some(table=>table.id===id)&&initialized.value&&id!==activeSavedId.value)request({kind:'switch',id});});
watch(()=>editable.value&&(dirty.value||editing.value!==undefined||settingsBusy.value||showEvidenceEditor.value),value=>emit('busy',value),{flush:'sync'});
onBeforeUnmount(()=>{mutationEpoch++;sequence++;emit('busy',false);});
</script>

<template>
 <section class="activity-comparison" data-activity-comparison>
  <header class="comparison-heading"><div><h2>{{t('活性对比')}}</h2><p>{{t('选择测定列，自动展示有相关数据的 Compound。')}}</p></div><button type="button" class="button-secondary" :disabled="loading" data-comparison-refresh @click="load">{{t('刷新')}}</button></header>
  <div :inert="settingsBusy" :aria-busy="settingsBusy">
  <div class="comparison-toolbar saved-toolbar">
   <label class="form-field">{{t('已保存的表格')}}<select data-saved-table :value="activeSavedId??''" :disabled="editing!==undefined||showEvidenceEditor" @change="request({kind:'switch',id:($event.target as HTMLSelectElement).value})"><option value="other">Other</option><option value="" disabled>{{t('未保存的表格')}}</option><option v-for="item in savedOptions" :key="item.id" :value="item.id">{{item.name}} · {{t('{columns} 列 / {compounds} 个 Compound',{columns:item.columns.length,compounds:item.compoundCount})}}</option></select></label>
   <template v-if="!isOther">
   <label class="form-field">{{t('表格名称')}}<input v-model="draft.name" data-table-name maxlength="512" :disabled="!mayMutate"></label>
   <div v-if="editable" class="editor-actions"><button type="button" class="button-secondary" data-save-table :disabled="!mayMutate||editing!==undefined" @click="saveTable">{{t('保存表格')}}</button><button v-if="activeSavedId" type="button" class="button-quiet" data-delete-table :disabled="!mayMutate||editing!==undefined" @click="request({kind:'delete'})">{{t('删除表格')}}</button></div>
   </template>
   <button v-if="editable" type="button" class="button-quiet" data-new-table :disabled="!mayMutate||editing!==undefined" @click="request({kind:'new'})">{{t('新建表格')}}</button>
  </div>
  <p v-if="isOther" class="settings-note" data-other-note>{{t('Other 自动显示尚未分配到任何表格的记录，包括正文、图及待核对归属的数据。')}}</p>
  <template v-else>
   <div class="comparison-toolbar" data-table-source>
    <label class="form-field">{{t('表格来源')}}<select v-model="draft.kind" data-table-kind :disabled="!mayMutate"><option value="source">{{t('原文 Table')}}</option><option value="custom">{{t('自定义表格')}}</option></select></label>
    <label class="form-field">{{t('原文表号')}}<input v-model="draft.source_label" data-source-label :disabled="!mayMutate" maxlength="512" placeholder="Table 1 / Table S1"></label>
    <label class="form-field">{{t('原文标题')}}<input v-model="draft.source_title" data-source-title :disabled="!mayMutate" maxlength="10000"></label>
    <label class="form-field">{{t('页码')}}<input v-model="draft.page_number" data-source-page :disabled="!mayMutate" type="number" min="1"></label>
    <span>{{draft.source_label}} {{draft.source_title}}</span>
   </div>
   <label v-if="editable" class="form-field">{{t('审核备注')}}<textarea v-model="draft.review_hint" data-table-review-hint :disabled="!mayMutate" maxlength="1000" /></label><ReviewHint v-else :hint="draft.review_hint" />
   <p v-if="activeSaved" data-table-review-status>{{t(activeSaved.review_status==='reviewer_confirmed'?'表格已确认。':activeSaved.review_status==='unresolved'?'表格无法判定。':'表格待 Reviewer 确认；AI 修订后需重新确认。')}} <button v-if="editable&&activeSaved.review_status!=='reviewer_confirmed'" type="button" class="button-secondary" data-confirm-table :disabled="!mayMutate||dirty||editing!==undefined||missingEvidence" @click="confirmTable()">{{t('确认表格')}}</button> <button v-if="editable&&activeSaved.review_status!=='unresolved'" type="button" class="button-quiet" data-unresolve-table :disabled="!mayMutate||dirty||editing!==undefined" @click="confirmTable('unresolved')">{{t('无法判定')}}</button></p>
  </template>
  <section v-if="!isOther" class="table-evidence-panel" data-table-evidence>
   <h3>{{t('原文 Table 截图')}}</h3>
   <p v-if="missingEvidence" data-table-evidence-missing class="inline-feedback is-warning">{{t('原文表确认前需关联有效的 Table 截图；缺失时可保存草稿或标记无法判定。')}}</p>
   <details v-if="editable"><summary>{{t('选择已有 Table Evidence（可多选）')}}</summary><label v-for="item in validEvidence" :key="item.id" class="evidence-choice"><input v-model="draft.evidence_ids" type="checkbox" data-table-evidence-choice :value="item.id" :disabled="!mayMutate||editing!==undefined||showEvidenceEditor">p{{item.page_number}} · {{item.caption||item.id}}</label></details>
   <p v-for="id in invalidLinkedEvidence" :key="id" class="inline-feedback is-warning">{{t('关联截图已失效')}} · {{id}} <button v-if="editable" type="button" class="button-quiet" :disabled="!mayMutate" @click="draft.evidence_ids=draft.evidence_ids.filter(value=>value!==id)">{{t('解除关联')}}</button></p>
   <TableEvidenceImages :evidence="linkedEvidence" :paper-id="workspace.bibliography.paper_id" :source-sha="workspace.source.sha256" :page-count="workspace.source.page_count" />
   <button v-if="editable" type="button" class="button-secondary" data-manage-table-evidence :disabled="blocked||dirty||editing!==undefined||loading||settingsBusy" @click="showEvidenceEditor=!showEvidenceEditor">{{t(showEvidenceEditor?'关闭证据编辑':'添加 / 重新框选 Table 截图')}}</button>
   <p v-if="editable&&dirty" class="settings-note">{{t('请先保存表格，再添加或修改截图。')}}</p>
   <EvidenceEditor v-if="showEvidenceEditor&&editable" :key="`${workspace.id}:${auth.user?.username}`" :workspace="{...workspace,version:loadedVersion}" :evidence-ids="draft.evidence_ids" activity-only table-only @mutated="evidenceMutated" @conflict="load" />
  </section>
  <p class="settings-note">{{t('表格随文章工作区保存，跨设备共享；活性数值始终引用最新记录。')}} <strong v-if="dirty">{{t('表格设置尚未保存。')}}</strong></p>
  <button v-if="editable&&legacy.length" type="button" class="button-secondary" data-import-local-tables :disabled="!mayMutate||dirty||editing!==undefined" @click="importLegacy">{{t('导入此浏览器的旧表格为自定义表格')}} ({{legacy.length}})</button>
  <p v-if="legacyError" role="alert">{{t(legacyError)}}</p><p v-if="notice" role="status">{{t(notice)}}</p><p v-if="storageError" role="alert" data-table-storage-error>{{t(storageError)}}</p>
  <div v-if="pending" class="pending-settings" role="alert"><p>{{t(pending.kind==='delete'?'删除这张已保存的表格配置？科学记录不会删除。':'当前表格设置尚未保存，是否放弃设置并继续？')}}</p><button type="button" class="button-secondary" data-discard-table-changes @click="perform(pending!)">{{t(pending.kind==='delete'?'删除表格':'放弃设置并继续')}}</button><button type="button" class="button-quiet" @click="pending=undefined">{{t('取消')}}</button></div>
  <div class="comparison-toolbar">
   <label class="form-field">{{t('搜索编号或名称')}}<input v-model="search" data-comparison-search type="search" :placeholder="t('搜索编号或名称')"></label>
   <label v-if="isOther||draft.compound_ids===null" class="form-field">{{t('显示范围')}}<select v-model="draft.mode" data-comparison-row-mode :disabled="!isOther&&editable&&!mayMutate"><option value="any">{{t('至少一列有记录')}}</option><option value="all">{{t('每列都有记录')}}</option></select></label>
   <label class="form-field">{{t('排序方式')}}<select v-model="draft.sort" data-comparison-sort :disabled="!isOther&&editable&&!mayMutate"><option value="label">{{t('名称排序')}}</option><option value="similarity">{{t('相似测定组合')}}</option><option value="default">{{t('表内行顺序')}}</option></select></label>
  </div>
  <section v-if="editable&&!isOther" class="row-config">
   <button type="button" class="button-quiet" data-toggle-row-config :disabled="!mayMutate||editing!==undefined" @click="showRows=!showRows">{{t('调整 Compound 行')}} ({{rowItems.length}})</button>
   <div v-if="showRows" :inert="!mayMutate||editing!==undefined">
    <p class="settings-note">{{t('移除行只解除本表记录归属；未被其他表引用的记录回到 Other。添加行后，可在列配置中选择具体记录。')}}</p>
    <div v-for="(compound,index) in rowItems" :key="compound.id" class="row-item"><span>{{compound.compound_label}} {{compound.display_name}}</span><button type="button" class="button-quiet" data-row-up :disabled="index===0" :aria-label="t('上移行')" @click="moveRow(index,index-1)">↑</button><button type="button" class="button-quiet" data-row-down :disabled="index===rowItems.length-1" :aria-label="t('下移行')" @click="moveRow(index,index+1)">↓</button><button type="button" class="button-quiet" data-row-remove @click="removeRow(compound.id)">{{t('移除')}}</button></div>
    <label class="form-field">{{t('搜索编号或名称')}}<input v-model="rowSearch" data-add-row-search type="search"></label>
    <label class="form-field">{{t('添加已有 Compound')}}<select v-model="addRowId" data-add-row-select><option value="">{{t('请选择')}}</option><option v-for="compound in rowChoices" :key="compound.id" :value="compound.id">{{compound.compound_label}} {{compound.display_name}}</option></select></label><button type="button" class="button-secondary" data-add-row :disabled="!addRowId" @click="addRow">{{t('添加行')}}</button>
   </div>
  </section>
  <div class="column-controls"><button v-if="editable&&isOther&&otherColumns.length" type="button" class="button-secondary" data-table-from-other :disabled="!mayMutate" @click="request({kind:'from-other'})">{{t('从 Other 创建表格')}}</button><button v-if="editable&&!isOther" type="button" class="button-primary" data-add-column :disabled="!mayMutate||!data?.activities.length||editing!==undefined||draft.columns.length>=200" @click="beginColumn(null)">{{t('添加列')}}</button><button v-if="columns.length&&!isOther&&editable" type="button" class="button-quiet" data-toggle-column-config :aria-expanded="showConfiguration" @click="showConfiguration=!showConfiguration">{{t(showConfiguration?'收起列配置':'配置列')}} ({{columns.length}})</button></div>
  <p v-if="columns.length" class="settings-note" data-suggestion-summary>{{t('当前表格：{columns} 列，{compounds} 个 Compound。',{columns:columns.length,compounds:table.rows.length})}}</p>
  <div v-show="showConfiguration" v-if="columns.length&&!isOther&&editable" class="configured-columns" data-configured-columns :inert="editing!==undefined">
   <div v-for="(column,index) in draft.columns" :key="column.id" class="configured-column" data-configured-column draggable="true" @dragstart="dragId=column.id; $event.dataTransfer?.setData('text/plain',column.id)" @dragend="dragId=undefined" @dragover.prevent @drop.prevent="dropColumn(index)">
    <div><strong>{{index+1}}. {{column.label}}</strong><small>{{column.assay}} · {{column.metric}} · {{column.unit||t('未记录单位')}}</small><small>{{t(column.activityIds===null?'全部记录（包含后续新增）':'仅选中记录')}} · {{table.matches.get(column.id)?.length??0}} {{t('条记录')}}</small></div>
    <div class="editor-actions"><button type="button" class="button-quiet" data-column-edit @click="beginColumn(column)">{{t('编辑列')}}</button><button type="button" class="button-quiet" data-column-move-left :disabled="index===0" :aria-label="t('左移列：{name}',{name:column.label})" @click="moveColumn(column.id,index-1)">←</button><button type="button" class="button-quiet" data-column-move-right :disabled="index===draft.columns.length-1" :aria-label="t('右移列：{name}',{name:column.label})" @click="moveColumn(column.id,index+1)">→</button><button type="button" class="button-quiet" data-column-remove @click="draft.columns.splice(index,1)">{{t('移除')}}</button></div>
   </div>
  </div>
  <div :inert="loading"><ActivityColumnEditor v-if="editable&&editing!==undefined&&data" :key="editorEpoch" :activities="data.activities" :compounds="data.compounds" :columns="draft.columns" :column="editing" @apply="applyColumn" @cancel="editing=undefined" /></div>
  <p v-if="blocked" class="inline-feedback is-warning">{{t('请先保存或取消当前编辑，再打开其他条目。')}}</p>
  <p v-if="loading" role="status">{{t('正在读取活性对比…')}}</p>
  <p v-if="error" role="alert">{{t(error)}} <button type="button" class="button-quiet" data-comparison-retry @click="load">{{t('重试')}}</button></p>
  <template v-if="data&&!error">
   <p v-if="!data.activities.length&&!loading">{{t('当前文章尚无活性记录。')}}</p>
   <p v-else-if="!columns.length&&!loading" data-comparison-empty>{{t(isOther?'Other 暂无未归属记录。':'点击“添加列”，选择要比较的测定和记录。')}}</p>
   <template v-else-if="!loading">
    <p v-for="column in columns.filter(c=>missingRecords(c)>0)" :key="column.id" class="inline-feedback is-warning" data-column-stale>{{t('列“{name}”有 {count} 条所选记录已删除或测定发生变化，请检查列设置。',{name:column.label,count:missingRecords(column)})}}</p>
    <p v-if="!compounds.length">{{t('没有符合当前列配置和显示范围的 Compound。')}}</p>
    <p class="comparison-coverage">{{t('显示 {shown}/{total} 个 Compound',{shown:compounds.length,total:data.compounds.length})}}</p>
   </template>
   <div v-show="!loading&&compounds.length>0" ref="viewport" class="comparison-scroll" data-comparison-scroll tabindex="0" role="region" :aria-label="t('Compound 活性对比表')" @scroll="rememberScroll">
    <table class="comparison-grid">
     <caption>{{t('— 表示无对应记录；条件与单位保留，同格多条记录全部列出。')}}</caption>
     <thead><tr><th scope="col" class="compound-column">Compound</th><th v-for="column in columns" :key="column.id" scope="col" data-comparison-column><span class="measurement-assay">{{column.label}}</span><small>{{column.metric}} · {{column.unit||t('未记录单位')}}</small><details class="measurement-context"><summary>{{t('关联测定')}}</summary><p>{{column.assay}}</p></details></th></tr></thead>
     <tbody><tr v-for="compound in compounds" :key="compound.id" data-comparison-row :data-compound-id="compound.id">
      <th scope="row" class="compound-column"><button type="button" class="comparison-link" data-comparison-compound :disabled="blocked||loading||dirty||editing!==undefined" @click="open(compound.id)">{{compound.compound_label}}</button><details v-if="compound.display_name" class="compound-name"><summary :title="compound.display_name">{{t('名称')}}</summary><small>{{compound.display_name}}</small></details><ReviewHint :hint="compound.review_hint" /></th>
      <td v-for="column in columns" :key="column.id"><template v-if="table.cells.get(compound.id)?.get(column.id)?.length"><div v-for="activity in table.cells.get(compound.id)?.get(column.id)" :key="activity.id" class="measurement-value"><button type="button" class="comparison-link" data-comparison-activity :data-activity-id="activity.id" :disabled="blocked||loading||dirty||editing!==undefined" :aria-label="t('查看 {compound} 的活性记录：{value}',{compound:compound.compound_label,value:`${activity.operator} ${activity.value} ${activity.unit??''}`})" @click="open(compound.id,activity.id)">{{activity.operator}} {{activity.value}}</button><ReviewHint :hint="activity.review_hint" /><details class="measurement-context record-context" data-measurement-context><summary :title="activity.context||t('未记录实验条件')">{{activity.context||t('未记录实验条件')}}</summary><p>{{activity.context||t('未记录实验条件')}}</p></details></div></template><span v-else class="missing-measurement">—</span></td>
     </tr></tbody>
    </table>
   </div>
  </template>
  </div>
 </section>
</template>
<style scoped>
.row-item,.evidence-choice{display:flex;align-items:center;gap:8px;margin:8px 0}.row-item span{flex:1}.evidence-choice input{width:auto}.table-evidence-panel{border:1px solid var(--line);padding:12px;border-radius:6px;margin:12px 0}
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

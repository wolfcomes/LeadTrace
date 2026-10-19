<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { t } from '../../i18n';
import type {Activity,Compound} from '../../v2/types';
import { columnSchema, matchingActivities, recommendMeasurements, type ComparisonColumn } from './activityTableBuilder';
const props=defineProps<{activities:Activity[];compounds:Compound[];columns:ComparisonColumn[];column:ComparisonColumn|null}>();
const emit=defineEmits<{apply:[column:ComparisonColumn];cancel:[]}>();
const groupQuery=ref(''),recordQuery=ref(''),label=ref(props.column?.label??'');
const selectedGroup=ref(props.column?JSON.stringify([props.column.assay,props.column.metric,props.column.unit]):'');
const scope=ref<'all'|'selected'>(props.column?.activityIds===null||!props.column?'all':'selected');
const selectedIds=ref<string[]>(props.column?.activityIds?[...props.column.activityIds]:[]);
const page=ref(0),pageSize=30,error=ref('');
const groups=computed(()=>recommendMeasurements(props.activities,props.columns));
const filteredGroups=computed(()=>groups.value.filter(g=>g.key===selectedGroup.value||`${g.assay} ${g.metric} ${g.unit??''}`.toLocaleLowerCase().includes(groupQuery.value.trim().toLocaleLowerCase())));
const group=computed(()=>groups.value.find(g=>g.key===selectedGroup.value));
const identity=computed(()=>group.value?{id:props.column?.id??'preview',label:label.value||'preview',assay:group.value.assay,metric:group.value.metric,unit:group.value.unit,activityIds:null}:props.column?{...props.column,activityIds:null}:null);
const records=computed(()=>identity.value?matchingActivities(identity.value,props.activities):[]);
const compoundsById=computed(()=>new Map(props.compounds.map(c=>[c.id,c])));
const filtered=computed(()=>{
 const query=recordQuery.value.trim().toLocaleLowerCase();
 return records.value.filter(a=>{const c=compoundsById.value.get(a.compound_id);return `${c?.compound_label??''} ${c?.display_name??''} ${a.context??''}`.toLocaleLowerCase().includes(query);});
});
const visible=computed(()=>filtered.value.slice(page.value*pageSize,(page.value+1)*pageSize));
const chosen=computed(()=>scope.value==='all'?records.value:records.value.filter(a=>selectedIds.value.includes(a.id)));
const compoundCount=computed(()=>new Set(chosen.value.map(a=>a.compound_id)).size);
function chooseGroup(key:string){
 selectedGroup.value=key;const g=groups.value.find(g=>g.key===key);
 label.value=g?`${g.assay} · ${g.metric}`:'';selectedIds.value=[];scope.value='all';recordQuery.value='';error.value='';
}
function toggle(id:string,checked:boolean){const ids=new Set(selectedIds.value);if(checked)ids.add(id);else ids.delete(id);selectedIds.value=[...ids];}
function selectFiltered(checked:boolean){const ids=new Set(selectedIds.value);for(const a of filtered.value){if(checked)ids.add(a.id);else ids.delete(a.id);}selectedIds.value=[...ids];}
function apply(){
 if(!identity.value)return;
 const parsed=columnSchema.safeParse({...identity.value,id:props.column?.id??crypto.randomUUID(),label:label.value.trim(),activityIds:scope.value==='all'?null:[...selectedIds.value]});
 if(!parsed.success){error.value='请填写列名并检查选择范围。';return;}
 emit('apply',parsed.data);
}
watch([recordQuery,selectedGroup],()=>{page.value=0;});
watch(()=>filtered.value.length,()=>{page.value=Math.min(page.value,Math.max(0,Math.ceil(filtered.value.length/pageSize)-1));});
</script>
<template>
 <section class="column-editor" data-column-editor :aria-label="t('配置对比列')">
  <header><h3>{{t(column?'编辑列':'添加列')}}</h3><button type="button" class="button-quiet" data-column-cancel @click="emit('cancel')">{{t('取消')}}</button></header>
  <div class="column-fields">
   <label class="form-field">{{t('查找测定')}}<input v-model="groupQuery" data-column-measurement-search type="search" :placeholder="t('输入测定名称、指标或单位')"></label>
   <label class="form-field measurement-field">{{t('关联测定')}}<select data-column-measurement :value="selectedGroup" @change="chooseGroup(($event.target as HTMLSelectElement).value)"><option value="" disabled>{{t('请选择测定分组')}}</option><option v-for="g in filteredGroups" :key="g.key" :value="g.key">{{g.assay}} · {{g.metric}} · {{g.unit||t('未记录单位')}} ({{g.compoundCount}} Compound{{g.sharedCompounds?` / ${t('共同')} ${g.sharedCompounds}`:''}})</option></select></label>
   <label class="form-field">{{t('显示列名')}}<input v-model="label" data-column-label maxlength="160"></label>
  </div>
  <template v-if="identity">
   <p class="column-identity">{{identity.assay}} · {{identity.metric}} · {{identity.unit||t('未记录单位')}}</p>
   <div class="column-fields">
    <label class="form-field">{{t('记录范围')}}<select v-model="scope" data-column-scope><option value="all">{{t('全部记录（包含后续新增）')}}</option><option value="selected">{{t('仅选中记录')}}</option></select></label>
    <label class="form-field measurement-field">{{t('筛选记录预览')}}<input v-model="recordQuery" data-column-record-search type="search" :placeholder="t('输入条件原文或 Compound 编号')"></label>
   </div>
   <p class="scope-note">{{t(scope==='all'?'筛选只改变预览；本列仍包含全部记录。':'筛选后勾选记录，或点击“选中筛选结果”。')}}</p>
   <div class="column-actions" v-if="scope==='selected'"><button type="button" class="button-secondary" data-column-select-filtered @click="selectFiltered(true)">{{t('选中筛选结果')}} ({{filtered.length}})</button><button type="button" class="button-quiet" @click="selectFiltered(false)">{{t('取消选中筛选结果')}}</button></div>
   <p data-column-selection-count>{{t('本列：{compounds} 个 Compound，{records} 条记录',{compounds:compoundCount,records:chosen.length})}}</p>
   <div class="record-preview" data-column-preview>
    <p v-if="!filtered.length">{{t('没有匹配的记录。')}}</p>
    <div v-for="activity in visible" :key="activity.id" class="record-choice" data-column-record>
     <input v-if="scope==='selected'" type="checkbox" :aria-label="t('选择记录：{compound} {value}',{compound:compoundsById.get(activity.compound_id)?.compound_label??'',value:activity.value})" :checked="selectedIds.includes(activity.id)" @change="toggle(activity.id,($event.target as HTMLInputElement).checked)">
     <div><strong>{{compoundsById.get(activity.compound_id)?.compound_label}}</strong> <span>{{activity.operator}} {{activity.value}} {{activity.unit}}</span><p>{{activity.context||t('未记录实验条件')}}</p></div>
    </div>
   </div>
   <div v-if="filtered.length>pageSize" class="column-actions"><button type="button" class="button-quiet" :disabled="page===0" @click="page--">{{t('上一页')}}</button><span>{{page+1}} / {{Math.ceil(filtered.length/pageSize)}}</span><button type="button" class="button-quiet" :disabled="(page+1)*pageSize>=filtered.length" @click="page++">{{t('下一页')}}</button></div>
  </template>
  <p v-if="error" role="alert">{{t(error)}}</p>
  <footer><button type="button" class="button-primary" data-column-apply :disabled="!identity||!label.trim()||!chosen.length" @click="apply">{{t(column?'应用列设置':'加入表格')}}</button></footer>
 </section>
</template>
<style scoped>
.column-editor { border: 1px solid var(--line); background: var(--paper); padding: 16px; border-radius: 6px; margin: 12px 0; min-width: 0; }
header, .column-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
header { justify-content: space-between; } h3 { margin: 0; }
.column-fields { display: flex; flex-wrap: wrap; gap: 12px; margin: 12px 0; }
.form-field { flex: 1 1 180px; min-width: 0; } .measurement-field { flex: 2 1 300px; }
input, select { width: 100%; } select { text-overflow: ellipsis; }
.column-identity, .scope-note { color: var(--muted); font-size: .8rem; overflow-wrap: anywhere; }
.record-preview { max-height: 280px; overflow: auto; border: 1px solid var(--line); border-radius: 4px; }
.record-choice { display: flex; align-items: flex-start; gap: 10px; padding: 8px; border-bottom: 1px solid var(--line); font-size: .8rem; }
.record-choice input { width: auto; min-height: auto; flex: 0 0 auto; margin-top: 4px; }
.record-choice div { min-width: 0; overflow-wrap: anywhere; }
.record-choice p { margin: 4px 0 0; color: var(--muted); white-space: pre-wrap; }
footer { margin-top: 12px; }
</style>

<script setup lang="ts">
import {computed} from 'vue';
import {rows,type Row} from './comparison';
import {reviewState} from './recordLabels';
import TableEvidenceImages from '../review/paper/TableEvidenceImages.vue';
import {t} from '../i18n';
const props=defineProps<{table:Row;snapshot:Record<string,unknown>;paperId?:string;currentSourceSha?:string}>();
const columns=computed(()=>Array.isArray(props.table.columns)?props.table.columns as Array<{id:string;label:string;assay:string;metric:string;unit:string|null;activity_ids:string[]}>:[]);
const activities=computed(()=>rows(props.snapshot,'activities'));
function matches(compound:Row,column:typeof columns.value[number]){return activities.value.filter(a=>a.compound_id===compound.id&&column.activity_ids.includes(String(a.id)));}
const compounds=computed(()=>{
 const all=rows(props.snapshot,'compounds');
 let selected=Array.isArray(props.table.compound_ids)?props.table.compound_ids.flatMap(id=>all.filter(c=>c.id===id)):all.filter(c=>columns.value.length&&(props.table.mode==='all'?columns.value.every(col=>matches(c,col).length):columns.value.some(col=>matches(c,col).length)));
 if(props.table.sort==='label')selected.sort((a,b)=>String(a.compound_label).localeCompare(String(b.compound_label),'en',{numeric:true,sensitivity:'base'}));
 return selected;
});
const source=computed(()=>props.snapshot.source as Row|undefined);
const evidence=computed(()=>Array.isArray(props.table.evidence_ids)?props.table.evidence_ids.flatMap(id=>rows(props.snapshot,'evidence').filter(e=>e.id===id)):[]);
const sourceMatches=computed(()=>!props.currentSourceSha||props.currentSourceSha===source.value?.sha256);
</script>
<template><section class="frozen-activity"><h4>{{table.name}}</h4><p>{{table.source_label}} {{table.source_title}}</p><p v-if="table.page_number">{{t('页码')}} {{table.page_number}}</p><p>{{reviewState(table.review_status)}}</p><p v-if="table.review_hint">{{table.review_hint}}</p><TableEvidenceImages v-if="paperId&&sourceMatches" :evidence="evidence" :paper-id="paperId" :source-sha="String(source?.sha256??'')" :page-count="Number(source?.page_count??0)" /><div class="table-scroll"><table class="frozen-matrix"><thead><tr><th>Compound</th><th v-for="column in columns" :key="column.id">{{column.label}}<small>{{column.assay}} · {{column.metric}} · {{column.unit}}</small></th></tr></thead><tbody><tr v-for="compound in compounds" :key="String(compound.id)"><th>{{compound.compound_label}}</th><td v-for="column in columns" :key="column.id"><template v-if="matches(compound,column).length"><div v-for="activity in matches(compound,column)" :key="String(activity.id)">{{activity.operator}} {{activity.value}}<details v-if="activity.context"><summary>{{t('实验条件')}}</summary>{{activity.context}}</details><p v-if="activity.review_hint">{{activity.review_hint}}</p></div></template><span v-else>—</span></td></tr></tbody></table></div></section></template>
<style scoped>
.frozen-activity{min-width:0;overflow-wrap:anywhere}.table-scroll{overflow:auto;max-height:65vh}.frozen-matrix{border-collapse:collapse;width:max-content;min-width:100%}th,td{border:1px solid var(--line);padding:8px;min-width:100px;max-width:220px;vertical-align:top}small{display:block;font-weight:normal}details{font-size:.8rem}.frozen-activity h4{margin:0}
</style>

<script setup lang="ts">
import { computed } from 'vue';
import { t } from '../i18n';
import type { PdbReference } from '../v2/workbench';
import type { ArticleSourceContext } from '../review/paper/articleMetadata';
import ArticleEvidence from '../review/paper/ArticleEvidence.vue';
import ReviewHint from '../review/paper/ReviewHint.vue';
import ReviewDisclosure from './ReviewDisclosure.vue';
const props=defineProps<{entries:PdbReference[];other:PdbReference[];side:'before'|'after';available:boolean;sourceContext?:ArticleSourceContext}>();
const pairs=computed(()=>{const before=props.side==='before'?props.entries:props.other,after=props.side==='after'?props.entries:props.other;const used=new Set<number>();return [...after.map(entry=>{let index=before.findIndex((old,i)=>!used.has(i)&&JSON.stringify(old)===JSON.stringify(entry));if(index<0){const candidates=before.map((old,i)=>({old,i})).filter(({old,i})=>!used.has(i)&&old.pdb_id===entry.pdb_id&&old.compound_label===entry.compound_label);if(candidates.length===1&&after.filter(x=>x.pdb_id===entry.pdb_id&&x.compound_label===entry.compound_label).length===1)index=candidates[0]!.i;}if(index>=0)used.add(index);return {before:index>=0?before[index]:undefined,after:entry};}),...before.filter((_,i)=>!used.has(i)).map(entry=>({before:entry,after:undefined}))];});
const usageLabels={this_work:'本文结构',cited_structure:'引用结构',unknown:'用途待核对'};
function syncScroll(event:Event) {const element=event.currentTarget as HTMLElement;const host=element.closest('[data-comparison-pair]');host?.querySelectorAll<HTMLElement>('[data-pdb-scroll]').forEach(other=>{if(other!==element&&Math.abs(other.scrollTop-element.scrollTop)>1)other.scrollTop=element.scrollTop;});}
</script>
<template><div class="pdb-comparison" data-pdb-comparison data-pdb-scroll tabindex="0" aria-label="PDB" @scroll="syncScroll"><div v-for="(pair,index) in pairs" :key="index" :data-profile-pair="`pdb:${index}`"><div data-profile-pair-content><template v-if="pair[side]"><strong>{{pair[side]!.pdb_id}}</strong> · {{t(usageLabels[pair[side]!.usage])}}<span v-if="pair[side]!.compound_label"> · Compound {{pair[side]!.compound_label}}</span><ReviewHint :hint="pair[side]!.review_hint" /><ReviewDisclosure :id="`article-pdb-evidence:${index}`" :label="t('依据与说明')" :expanded="available && !!pair.before && !!pair.after && JSON.stringify(pair.before)!==JSON.stringify(pair.after)"><ArticleEvidence :evidence="pair[side]!.evidence" :source-context="sourceContext" /><p v-if="pair[side]!.source_page">PDF p. {{pair[side]!.source_page}}</p><p>{{pair[side]!.source_context}}</p><p>{{pair[side]!.review_hint}}</p></ReviewDisclosure></template><p v-else>{{t('未记录')}}</p></div></div></div></template>
<style scoped>.pdb-comparison{max-height:360px;overflow:auto;scrollbar-gutter:stable}.pdb-comparison>[data-profile-pair]{padding:.7rem;border:1px solid var(--line);border-radius:6px;margin-bottom:.5rem}</style>

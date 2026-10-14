<script setup lang="ts">
import { computed } from 'vue';
import { t } from '../../i18n';
import { profileGroups, targetRoleLabels, modalityLabel, type ResearchProfile } from './articleMetadata';
import ReviewHint from './ReviewHint.vue';
import ArticleEvidence from './ArticleEvidence.vue';
import type { ArticleSourceContext } from './articleMetadata';
const props=defineProps<{profile:ResearchProfile;sourceContext?:ArticleSourceContext;hideHeadings?:boolean;preserveTargetOrder?:boolean;evidenceChanges?:Partial<Record<keyof ResearchProfile,number[]>>}>();
const targets=computed(()=>props.profile.targets?.map((target,index)=>({target,index})).sort((a,b)=>props.preserveTargetOrder?0:Number(['primary','co_primary'].includes(b.target.role))-Number(['primary','co_primary'].includes(a.target.role)))??[]);
const expanded=(key:keyof ResearchProfile,index:number)=>props.evidenceChanges?.[key]?.includes(index)??false;
</script>
<template><div class="research-profile" data-research-profile>
  <template v-for="group in profileGroups" :key="group.key"><section v-if="profile[group.key]?.length" :data-profile-group="group.key">
    <h4 v-if="!hideHeadings">{{t(group.label)}}</h4><ul><li v-for="(term,index) in profile[group.key]" :key="index">
      <div class="profile-title"><strong>{{group.key==='modalities' ? t(modalityLabel(term.label)??term.label) : term.label}}</strong><span v-if="group.key==='modalities' && !modalityLabel(term.label)" class="legacy-warning">{{t('旧词条，待选择')}}</span><ReviewHint :hint="term.review_hint" /></div>
      <details :open="expanded(group.key,index)" data-term-evidence><summary>{{t('依据与说明')}}</summary><p v-if="group.key==='modalities' && modalityLabel(term.label)!==term.label">{{t('原始词条')}}：{{term.label}}</p><ArticleEvidence :evidence="term.evidence" :source-context="sourceContext" /><small>{{t('依据说明')}}：{{term.source}}</small><p v-if="term.review_hint">{{term.review_hint}}</p></details>
    </li></ul>
  </section></template>
  <section v-if="targets.length" data-profile-group="targets"><h4 v-if="!hideHeadings">{{t('研究靶点与关联基因')}}</h4><ul><li v-for="{target,index} in targets" :key="index" data-target-card>
    <div class="profile-title"><strong>{{target.name}}</strong><span class="role-tag">{{t(targetRoleLabels[target.role])}}</span><ReviewHint :hint="target.review_hint" /></div>
    <p class="target-identity" v-if="target.gene_symbol || target.organism"><span v-if="target.gene_symbol">{{target.gene_symbol}}</span><span v-if="target.organism">{{target.organism}}</span></p>
    <details :open="expanded('targets',index)" data-target-evidence><summary>{{t('编号与依据')}}</summary><ArticleEvidence :evidence="target.evidence" :source-context="sourceContext" /><p v-if="target.uniprot_id || target.ncbi_gene_id"><span v-if="target.uniprot_id">UniProt: {{target.uniprot_id}} </span><span v-if="target.ncbi_gene_id">NCBI Gene: {{target.ncbi_gene_id}}</span></p><small>{{t('依据说明')}}：{{target.source}}</small><p v-if="target.review_hint">{{target.review_hint}}</p></details>
  </li></ul></section>
</div></template>
<style scoped>
h4 {margin:1rem 0 .5rem;color:var(--ink-muted);font-size:.88rem} ul {list-style:none;padding:0;margin:0;display:grid;gap:.5rem} li {padding:.7rem .85rem;border:1px solid var(--line);border-radius:6px;overflow-wrap:anywhere;min-width:0} small {display:block;color:var(--ink-muted);white-space:pre-wrap} p {margin:.4rem 0;white-space:pre-wrap} strong {font-weight:600} .profile-title {display:flex;align-items:center;gap:.5rem;flex-wrap:wrap}.role-tag {font-size:.75rem;color:var(--ink-muted);border:1px solid var(--line);border-radius:1rem;padding:.1rem .5rem}.target-identity {display:flex;gap:.75rem;flex-wrap:wrap;font-size:.88rem}.legacy-warning{color:var(--amber);font-size:.8rem}details{margin-top:.45rem;font-size:.85rem}summary{cursor:pointer;color:var(--ink-muted)}
</style>

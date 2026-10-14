<script setup lang="ts">
import { t } from '../../i18n';
import { profileGroups, targetRoleLabels, type ResearchProfile } from './articleMetadata';
import ReviewHint from './ReviewHint.vue';
defineProps<{profile:ResearchProfile;hideHeadings?:boolean}>();
</script>
<template><div class="research-profile" data-research-profile>
  <template v-for="group in profileGroups" :key="group.key"><section v-if="profile[group.key]?.length" :data-profile-group="group.key">
    <h4 v-if="!hideHeadings">{{t(group.label)}}</h4><ul><li v-for="(term,index) in profile[group.key]" :key="index">
      <strong>{{term.label}}</strong><small>{{t('来源')}}：{{term.source}}</small><ReviewHint :hint="term.review_hint" />
    </li></ul>
  </section></template>
  <section v-if="profile.targets?.length" data-profile-group="targets"><h4 v-if="!hideHeadings">{{t('研究靶点与关联基因')}}</h4><ul><li v-for="(target,index) in profile.targets" :key="index">
    <strong>{{target.name}}</strong> · {{t(targetRoleLabels[target.role])}}
    <p v-if="target.gene_symbol || target.organism">{{target.gene_symbol}}<span v-if="target.organism"> · {{target.organism}}</span></p>
    <p v-if="target.uniprot_id || target.ncbi_gene_id"><span v-if="target.uniprot_id">UniProt: {{target.uniprot_id}} </span><span v-if="target.ncbi_gene_id">NCBI Gene: {{target.ncbi_gene_id}}</span></p>
    <small>{{t('来源')}}：{{target.source}}</small><ReviewHint :hint="target.review_hint" />
  </li></ul></section>
</div></template>
<style scoped>
h4 {margin:.8rem 0 .4rem;color:var(--ink-muted);font-size:.85rem} ul {list-style:none;padding:0;margin:0;display:grid;gap:.5rem} li {padding:.55rem .7rem;border:1px solid var(--line);border-radius:5px;overflow-wrap:anywhere} small {display:block;color:var(--ink-muted);white-space:pre-wrap} p {margin:.25rem 0} strong {font-weight:600}
</style>

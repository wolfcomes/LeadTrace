<script setup lang="ts">
import { computed } from 'vue';
import { t } from '../i18n';
import { profileGroups, type ResearchProfile } from '../review/paper/articleMetadata';
import ResearchProfileView from '../review/paper/ResearchProfile.vue';
import ReviewDisclosure from './ReviewDisclosure.vue';
import { pairProfileEntries, profileEvidenceChanged } from './researchProfilePairs';
const props=withDefaults(defineProps<{profile:ResearchProfile;other:ResearchProfile;available:boolean;side?:'before'|'after'}>(),{side:'after'});
const groups=computed(()=>[...profileGroups,{key:'targets' as const,label:'研究靶点与关联基因'}].map(group=>({
  ...group,changed:!props.available||JSON.stringify(props.profile[group.key]??[])!==JSON.stringify(props.other[group.key]??[]),
  pairs:pairProfileEntries((props.side==='before'?props.profile:props.other)[group.key]??[],(props.side==='after'?props.profile:props.other)[group.key]??[]),
})).filter(group=>group.pairs.length).sort((a,b)=>Number(b.changed)-Number(a.changed)));
</script>
<template><div data-profile-comparison><ReviewDisclosure v-for="group in groups" :key="group.key" :id="`research-profile:${group.key}`" :label="t(group.label)" :expanded="group.changed" :class="{'profile-group-changed':group.changed && available}" :data-profile-diff-group="group.key">
  <div v-for="(pair,index) in group.pairs" :key="index" class="profile-pair-entry" :data-profile-pair="`${group.key}:${index}`"><ResearchProfileView v-if="pair[side]" :profile="{[group.key]:[pair[side]]}" hide-headings preserve-target-order :evidence-changes="{[group.key]:available && profileEvidenceChanged(pair)?[0]:[]}" /><p v-else>{{t('未记录')}}</p></div>
</ReviewDisclosure></div></template>
<style scoped>.profile-group-changed {background:var(--amber-pale);border-radius:4px;padding:.25rem}.profile-pair-entry+.profile-pair-entry{margin-top:.5rem}</style>

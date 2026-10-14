<script setup lang="ts">
import { computed } from 'vue';
import { t } from '../i18n';
import { profileGroups, type ResearchProfile } from '../review/paper/articleMetadata';
import ResearchProfileView from '../review/paper/ResearchProfile.vue';
import ReviewDisclosure from './ReviewDisclosure.vue';
const props=defineProps<{profile:ResearchProfile;other:ResearchProfile;available:boolean}>();
const groups=computed(()=>[...profileGroups,{key:'targets' as const,label:'研究靶点与关联基因'}].map(group=>({
  ...group,changed:!props.available||JSON.stringify(props.profile[group.key]??[])!==JSON.stringify(props.other[group.key]??[]),
})).filter(group=>props.profile[group.key]?.length||props.other[group.key]?.length).sort((a,b)=>Number(b.changed)-Number(a.changed)));
</script>
<template><div data-profile-comparison><ReviewDisclosure v-for="group in groups" :key="group.key" :id="`research-profile:${group.key}`" :label="t(group.label)" :expanded="group.changed" :class="{'profile-group-changed':group.changed && available}" :data-profile-diff-group="group.key">
  <ResearchProfileView v-if="profile[group.key]?.length" :profile="{[group.key]:profile[group.key]}" hide-headings /><p v-else>{{t('未记录')}}</p>
</ReviewDisclosure></div></template>

<style scoped>.profile-group-changed {background:var(--amber-pale);border-radius:4px;padding:.25rem} </style>

<script setup lang="ts">
import { computed } from 'vue';
import { t } from '../i18n';
import { profileGroups, type ResearchProfile, type ArticleSourceContext } from '../review/paper/articleMetadata';
import ResearchProfileView from '../review/paper/ResearchProfile.vue';
import ReviewDisclosure from './ReviewDisclosure.vue';
import { pairProfileEntries, profileEvidenceChanged } from './researchProfilePairs';
const props=withDefaults(defineProps<{profile:ResearchProfile;sourceContext?:ArticleSourceContext;other:ResearchProfile;available:boolean;side?:'before'|'after'}>(),{side:'after'});
const groups=computed(()=>[...profileGroups,{key:'targets' as const,label:'研究靶点与关联基因'}].map(group=>({
  ...group,changed:!props.available||JSON.stringify(props.profile[group.key]??[])!==JSON.stringify(props.other[group.key]??[]),
  pairs:pairProfileEntries((props.side==='before'?props.profile:props.other)[group.key]??[],(props.side==='after'?props.profile:props.other)[group.key]??[]),
})).filter(group=>group.pairs.length).sort((a,b)=>Number(b.changed)-Number(a.changed)));
function syncScroll(event:Event) {const element=event.currentTarget as HTMLElement;const host=element.closest('[data-comparison-pair]');host?.querySelectorAll<HTMLElement>('[data-profile-scroll]').forEach(other=>{if(other!==element&&other.dataset.profileScroll===element.dataset.profileScroll&&Math.abs(other.scrollTop-element.scrollTop)>1)other.scrollTop=element.scrollTop;});}
</script>
<template><div data-profile-comparison><ReviewDisclosure v-for="group in groups" :key="group.key" :id="`research-profile:${group.key}`" :label="t(group.label)" :expanded="group.changed" :class="{'profile-group-changed':group.changed && available}" :data-profile-diff-group="group.key">
  <div class="profile-group-scroll" :data-profile-scroll="group.key" tabindex="0" :aria-label="t(group.label)" @scroll="syncScroll"><div v-for="(pair,index) in group.pairs" :key="index" class="profile-pair-entry" :data-profile-pair="`${group.key}:${index}`"><div data-profile-pair-content><ResearchProfileView v-if="pair[side]" :profile="{[group.key]:[pair[side]]}" :source-context="sourceContext" hide-headings preserve-target-order :evidence-changes="{[group.key]:available && profileEvidenceChanged(pair)?[0]:[]}" /><p v-else>{{t('未记录')}}</p></div></div></div>
</ReviewDisclosure></div></template>
<style scoped>.profile-group-changed {background:var(--amber-pale);border-radius:4px;padding:.25rem}.profile-pair-entry+.profile-pair-entry{margin-top:.5rem}.profile-group-scroll{max-height:360px;overflow:auto;scrollbar-gutter:stable;overscroll-behavior:contain;padding:.25rem}@media(max-width:760px){.profile-group-scroll{max-height:480px}}</style>

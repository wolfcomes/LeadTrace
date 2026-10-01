<script setup lang="ts">
import { computed } from 'vue';
import { t } from '../../i18n';
import { highlightRole,highlightStatus } from '../../v2/highlights';
import { useHighlights } from './useHighlights';
const props=defineProps<{compoundId:string}>();
const state=useHighlights();
const items=computed(()=>state?.items.value.filter(x=>x.compound_id===props.compoundId)??[]);
</script>
<template><span v-if="items.length" class="highlight-badges"><details v-for="item in items" :key="item.id" class="highlight-badge" :data-highlight-status="item.review_status"><summary>{{ t(highlightRole(item.role)) }} · {{ t(highlightStatus(item.review_status)) }}</summary><p>{{ item.scope }} · {{ item.rationale }}</p><p v-if="item.review_hint">⚠ {{ item.review_hint }}</p><details><summary>{{ t('来源 Evidence') }} · {{ t('PDF 页码') }} {{ state?.evidence.value.find(x=>x.id===item.evidence_id)?.page_number??'?' }}</summary><p>{{ state?.evidence.value.find(x=>x.id===item.evidence_id)?.caption }}</p><blockquote>{{ state?.evidence.value.find(x=>x.id===item.evidence_id)?.quoted_text }}</blockquote></details></details></span></template>
<style scoped>.highlight-badges{display:flex;gap:6px;flex-wrap:wrap}.highlight-badge{font-size:12px;padding:3px 7px;border:1px solid var(--line-strong);border-radius:8px}.highlight-badge[data-highlight-status="reviewer_confirmed"]{background:var(--teal-pale)}.highlight-badge p{max-width:32rem;white-space:normal}</style>

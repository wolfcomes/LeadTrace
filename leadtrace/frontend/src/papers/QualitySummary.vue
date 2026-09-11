<script setup lang="ts">
import type { QualitySummary } from "../api/schema";
import { zhCN } from "../i18n/zh-CN";


defineProps<{ summary: QualitySummary }>();
</script>

<template>
  <div class="quality-grid">
    <article>
      <span>{{ zhCN.published.quality.relations }}</span>
      <strong>{{ summary.relations.resolved }} / {{ summary.relations.total }}</strong>
    </article>
    <article>
      <span>{{ zhCN.published.quality.structures }}</span>
      <strong>{{ summary.structures.confirmed }} / {{ summary.structures.total }}</strong>
    </article>
    <article>
      <span>{{ zhCN.published.quality.pairReady }}</span>
      <strong>{{ summary.pair_ready.eligible }} / {{ summary.pair_ready.total }}</strong>
    </article>
    <article>
      <span>{{ zhCN.published.quality.humanReview }}</span>
      <strong>{{ summary.human_review.reviewed }} / {{ summary.human_review.total }}</strong>
    </article>
  </div>
</template>

<style scoped>
.quality-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.quality-grid article { padding: 17px; border: 1px solid var(--line); border-radius: 11px; background: white; box-shadow: var(--shadow-sm); }
.quality-grid span, .quality-grid strong { display: block; }
.quality-grid span { color: var(--ink-500); font-size: .7rem; }
.quality-grid strong { margin-top: 8px; color: var(--ink-950); font: 600 1.18rem/1.2 Georgia, "Noto Serif SC Variable", serif; }
@media (max-width: 820px) { .quality-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 440px) { .quality-grid { grid-template-columns: 1fr; } }
</style>

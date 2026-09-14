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

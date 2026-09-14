<script setup lang="ts">
import { onMounted, ref } from "vue";

import { ApiError } from "../api/client";
import { fetchOverview } from "../api/published";
import type { OverviewResponse } from "../api/schema";
import { zhCN } from "../i18n/zh-CN";
import ReleaseVerificationBadge from "./ReleaseVerificationBadge.vue";


type ViewState = "loading" | "ready" | "empty" | "error";

const state = ref<ViewState>("loading");
const overview = ref<OverviewResponse | null>(null);
const requestId = ref<string | undefined>();

const metricCards = [
  { key: "corpus", label: zhCN.published.overview.corpus, note: zhCN.published.overview.metricNotes.corpus },
  { key: "lineage", label: zhCN.published.overview.lineage, note: zhCN.published.overview.metricNotes.lineage },
  { key: "relation", label: zhCN.published.overview.relation, note: zhCN.published.overview.metricNotes.relation },
  { key: "structure", label: zhCN.published.overview.structure, note: zhCN.published.overview.metricNotes.structure },
  { key: "pair", label: zhCN.published.overview.pair, note: zhCN.published.overview.metricNotes.pair },
  { key: "human_review", label: zhCN.published.overview.humanReview, note: zhCN.published.overview.metricNotes.humanReview },
] as const;

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Shanghai",
  }).format(new Date(value));
}

async function load(): Promise<void> {
  state.value = "loading";
  requestId.value = undefined;
  try {
    overview.value = await fetchOverview();
    state.value = "ready";
  } catch (error) {
    overview.value = null;
    if (error instanceof ApiError) {
      requestId.value = error.requestId;
      state.value = error.code === "CURRENT_RELEASE_NOT_FOUND" ? "empty" : "error";
    } else {
      state.value = "error";
    }
  }
}

onMounted(load);
</script>

<template>
  <div class="published-page overview-page">
    <header class="page-heading page-heading--editorial">
      <div>
        <p class="eyebrow">{{ zhCN.published.overview.eyebrow }}</p>
        <h1>{{ zhCN.published.overview.title }}</h1>
        <p class="page-description">{{ zhCN.published.overview.description }}</p>
      </div>
      <div v-if="overview" class="release-card">
        <span>{{ zhCN.published.overview.releaseLabel }}</span>
        <strong>{{ overview.release.title }}</strong>
        <ReleaseVerificationBadge :status="overview.release.verification_status" />
        <code>{{ overview.release.key }}</code>
        <small>{{ zhCN.published.overview.publishedAt }} · {{ formatDate(overview.release.published_at) }}</small>
      </div>
    </header>

    <section v-if="state === 'loading'" class="page-state" aria-live="polite">
      <span class="state-spinner" aria-hidden="true"></span>
      <p>{{ zhCN.published.states.loading }}</p>
    </section>

    <section v-else-if="state === 'empty'" class="page-state" data-empty-state>
      <span class="state-symbol" aria-hidden="true">—</span>
      <h2>{{ zhCN.published.states.emptyTitle }}</h2>
      <p>{{ zhCN.published.states.emptyBody }}</p>
    </section>

    <section v-else-if="state === 'error'" class="page-state" role="alert">
      <span class="state-symbol is-error" aria-hidden="true">!</span>
      <h2>{{ zhCN.published.states.errorTitle }}</h2>
      <p>{{ zhCN.published.states.errorBody }}</p>
      <small v-if="requestId">{{ zhCN.published.states.requestId }} · {{ requestId }}</small>
      <button class="button-secondary" type="button" @click="load">{{ zhCN.published.states.retry }}</button>
    </section>

    <section v-else-if="overview" class="metric-grid" aria-label="发布数据指标">
      <article
        v-for="(card, index) in metricCards"
        :key="card.key"
        class="metric-card metric-card--dashboard"
        :class="{ primary: index < 2 }"
        :data-metric="card.key"
      >
        <div class="metric-number">0{{ index + 1 }}</div>
        <div>
          <span class="metric-label">{{ card.label }}</span>
          <strong>{{ overview.metrics[card.key].numerator }} / {{ overview.metrics[card.key].denominator }}</strong>
          <p>{{ card.note }}</p>
        </div>
        <span class="metric-unit">{{ overview.metrics[card.key].unit }}</span>
      </article>
    </section>
  </div>
</template>

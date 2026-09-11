<script setup lang="ts">
import { onMounted, ref } from "vue";

import { ApiError } from "../api/client";
import { fetchOverview } from "../api/published";
import type { OverviewResponse } from "../api/schema";
import { zhCN } from "../i18n/zh-CN";


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
    <header class="page-heading">
      <div>
        <p class="eyebrow">{{ zhCN.published.overview.eyebrow }}</p>
        <h1>{{ zhCN.published.overview.title }}</h1>
        <p class="page-description">{{ zhCN.published.overview.description }}</p>
      </div>
      <div v-if="overview" class="release-card">
        <span>{{ zhCN.published.overview.releaseLabel }}</span>
        <strong>{{ overview.release.title }}</strong>
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
        class="metric-card"
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

<style scoped>
.overview-page { padding: clamp(30px, 5vw, 58px); }
.page-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 48px; max-width: 1280px; margin: 0 auto 34px; }
.page-heading h1 { margin: 0; color: var(--ink-950); font: 600 clamp(2rem, 3vw, 3.1rem)/1.15 Georgia, "Noto Serif SC Variable", serif; letter-spacing: -.025em; }
.page-description { max-width: 690px; margin: 16px 0 0; color: var(--ink-650); font-size: .9rem; line-height: 1.8; }
.release-card { width: min(100%, 330px); flex: 0 0 330px; padding: 18px 20px; border: 1px solid #d8c89f; border-radius: var(--radius-md); background: linear-gradient(145deg, #fffef9, var(--gold-100)); box-shadow: var(--shadow-sm); }
.release-card span, .release-card strong, .release-card code, .release-card small { display: block; }
.release-card span { color: var(--gold-700); font-size: .64rem; font-weight: 800; letter-spacing: .1em; }
.release-card strong { margin-top: 8px; color: var(--ink-950); font: 600 1rem/1.35 Georgia, "Noto Serif SC Variable", serif; }
.release-card code { margin-top: 8px; color: var(--ink-650); font-size: .68rem; overflow-wrap: anywhere; }
.release-card small { margin-top: 13px; color: var(--ink-500); font-size: .66rem; }
.metric-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; max-width: 1280px; margin: auto; }
.metric-card { position: relative; display: grid; min-height: 190px; grid-template-columns: 46px minmax(0, 1fr) auto; gap: 18px; padding: 25px; overflow: hidden; border: 1px solid var(--line); border-radius: var(--radius-md); background: white; box-shadow: var(--shadow-sm); }
.metric-card.primary { min-height: 230px; padding: 30px; border-color: #cbd9d1; background: linear-gradient(145deg, white 55%, var(--forest-100)); }
.metric-number { color: #b9c3bd; font: 500 .72rem/1.2 ui-monospace, SFMono-Regular, Consolas, monospace; }
.metric-label { color: var(--ink-650); font-size: .75rem; font-weight: 740; letter-spacing: .04em; }
.metric-card strong { display: block; margin-top: 20px; color: var(--ink-950); font: 600 clamp(1.75rem, 3vw, 2.8rem)/1 Georgia, "Noto Serif SC Variable", serif; letter-spacing: -.025em; }
.metric-card p { max-width: 410px; margin: 19px 0 0; color: var(--ink-500); font-size: .75rem; line-height: 1.65; }
.metric-unit { align-self: start; padding: 5px 8px; border-radius: 999px; color: var(--forest-750); background: var(--forest-100); font-size: .62rem; font-weight: 700; }
.page-state { display: grid; max-width: 760px; min-height: 300px; place-items: center; align-content: center; margin: 48px auto; padding: 44px; border: 1px solid var(--line); border-radius: var(--radius-lg); background: white; text-align: center; box-shadow: var(--shadow-sm); }
.page-state h2 { margin: 16px 0 0; color: var(--ink-950); font: 600 1.5rem/1.3 Georgia, "Noto Serif SC Variable", serif; }
.page-state p { max-width: 520px; margin: 11px 0 0; color: var(--ink-650); line-height: 1.7; }
.page-state small { margin-top: 13px; color: var(--ink-500); }
.state-symbol { display: grid; width: 42px; height: 42px; place-items: center; border-radius: 50%; color: var(--gold-700); background: var(--gold-100); font-weight: 800; }
.state-symbol.is-error { color: var(--danger); background: var(--danger-soft); }
.state-spinner { width: 28px; height: 28px; border: 3px solid var(--forest-100); border-top-color: var(--forest-750); border-radius: 50%; animation: spin .8s linear infinite; }
.button-secondary { min-height: 40px; margin-top: 20px; padding: 8px 15px; border: 1px solid var(--forest-750); border-radius: var(--radius-sm); color: var(--forest-750); background: white; font-weight: 700; cursor: pointer; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 860px) { .page-heading { flex-direction: column; gap: 24px; } .release-card { width: 100%; flex-basis: auto; } .metric-grid { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { .state-spinner { animation: none; } }
</style>

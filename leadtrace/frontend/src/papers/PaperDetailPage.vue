<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { ApiError } from "../api/client";
import { fetchPaperDetail } from "../api/published";
import type { PaperDetailResponse } from "../api/schema";
import EvidenceCard from "../evidence/EvidenceCard.vue";
import { zhCN } from "../i18n/zh-CN";
import LineageView from "../lineages/LineageView.vue";
import QualitySummary from "./QualitySummary.vue";


type ViewState = "loading" | "ready" | "not-found" | "empty-release" | "error";

const route = useRoute();
const state = ref<ViewState>("loading");
const detail = ref<PaperDetailResponse | null>(null);
const requestId = ref<string | undefined>();

const confirmedStructures = computed(() => detail.value?.structures.filter(
  (structure) => structure.state === "structure_confirmed" && structure.canonical_smiles,
) ?? []);

const compoundLabels = computed(() => new Map(
  detail.value?.compounds.map((compound) => [compound.id, compound.label]) ?? [],
));

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Shanghai",
  }).format(new Date(value));
}

async function load(): Promise<void> {
  state.value = "loading";
  detail.value = null;
  requestId.value = undefined;
  const paperId = String(route.params.paperId ?? "");
  try {
    detail.value = await fetchPaperDetail(paperId);
    state.value = "ready";
  } catch (error) {
    if (error instanceof ApiError) {
      requestId.value = error.requestId;
      if (error.code === "CURRENT_RELEASE_NOT_FOUND") state.value = "empty-release";
      else if (error.code === "RESOURCE_NOT_FOUND") state.value = "not-found";
      else state.value = "error";
    } else {
      state.value = "error";
    }
  }
}

watch(() => route.params.paperId, load, { immediate: true });
</script>

<template>
  <div class="published-page detail-page">
    <RouterLink class="back-link" :to="{ name: 'papers' }">← {{ zhCN.published.detail.back }}</RouterLink>

    <section v-if="state === 'loading'" class="page-state" aria-live="polite">
      <span class="state-spinner" aria-hidden="true"></span>
      <p>{{ zhCN.published.states.loading }}</p>
    </section>

    <section v-else-if="state === 'empty-release'" class="page-state" data-empty-state>
      <span class="state-symbol" aria-hidden="true">—</span>
      <h1>{{ zhCN.published.states.emptyTitle }}</h1>
      <p>{{ zhCN.published.states.emptyBody }}</p>
    </section>

    <section v-else-if="state === 'not-found'" class="page-state">
      <span class="state-symbol" aria-hidden="true">404</span>
      <h1>未找到已发布文献</h1>
      <p>该编号不属于当前发布版本，或文献已不可见。</p>
      <small v-if="requestId">{{ zhCN.published.states.requestId }} · {{ requestId }}</small>
    </section>

    <section v-else-if="state === 'error'" class="page-state" role="alert">
      <span class="state-symbol is-error" aria-hidden="true">!</span>
      <h1>{{ zhCN.published.states.errorTitle }}</h1>
      <p>{{ zhCN.published.states.errorBody }}</p>
      <small v-if="requestId">{{ zhCN.published.states.requestId }} · {{ requestId }}</small>
      <button class="button-secondary" type="button" @click="load">{{ zhCN.published.states.retry }}</button>
    </section>

    <template v-else-if="detail">
      <header class="paper-hero">
        <div class="hero-main">
          <div class="paper-identifiers">
            <span>{{ zhCN.published.detail.stableId }} <code>{{ detail.paper.paper_key }}</code></span>
            <span v-if="detail.paper.doi">{{ zhCN.published.detail.doi }} <code>{{ detail.paper.doi }}</code></span>
          </div>
          <h1>{{ detail.paper.title }}</h1>
          <div class="hero-tags">
            <span>{{ zhCN.published.detail.year }} · {{ detail.paper.year || "—" }}</span>
            <span>{{ zhCN.published.detail.target }} · {{ detail.paper.target || "—" }}</span>
            <span>{{ detail.paper.review_status || "—" }}</span>
          </div>
        </div>
        <aside class="release-card">
          <span>{{ zhCN.published.detail.release }}</span>
          <strong>{{ detail.release.title }}</strong>
          <code>{{ detail.release.key }}</code>
          <small>{{ zhCN.published.detail.publishedAt }} · {{ formatDate(detail.release.published_at) }}</small>
        </aside>
      </header>

      <section class="content-section quality-section">
        <div class="section-heading">
          <div>
            <p class="eyebrow">QUALITY SIGNALS</p>
            <h2>{{ zhCN.published.detail.quality }}</h2>
          </div>
        </div>
        <QualitySummary :summary="detail.quality_summary" />
      </section>

      <section class="content-section">
        <div class="section-heading">
          <div>
            <p class="eyebrow">LINEAGE</p>
            <h2>{{ zhCN.published.detail.lineage }}</h2>
          </div>
          <span>{{ detail.lineages.length }} lineages · {{ detail.lineage_edges.length }} edges</span>
        </div>
        <LineageView
          v-if="detail.lineages.length"
          :lineages="detail.lineages"
          :edges="detail.lineage_edges"
          :compounds="detail.compounds"
          :structures="detail.structures"
        />
        <p v-else class="section-empty">{{ zhCN.published.detail.noLineage }}</p>
      </section>

      <section class="content-section">
        <div class="section-heading">
          <div>
            <p class="eyebrow">CONFIRMED CHEMISTRY</p>
            <h2>{{ zhCN.published.detail.structures }}</h2>
          </div>
          <span>{{ confirmedStructures.length }} confirmed</span>
        </div>
        <div v-if="confirmedStructures.length" class="structure-grid">
          <article v-for="structure in confirmedStructures" :key="structure.id" data-confirmed-structure>
            <div class="structure-label">
              <span>{{ zhCN.published.structure.confirmedData }}</span>
              <strong>{{ compoundLabels.get(structure.compound_id) || "—" }}</strong>
            </div>
            <small>{{ zhCN.published.structure.smiles }}</small>
            <code>{{ structure.canonical_smiles }}</code>
          </article>
        </div>
        <p v-else class="section-empty">{{ zhCN.published.detail.noStructures }}</p>
      </section>

      <section class="content-section split-section">
        <div>
          <div class="section-heading">
            <div>
              <p class="eyebrow">EVIDENCE</p>
              <h2>{{ zhCN.published.detail.evidence }}</h2>
            </div>
          </div>
          <div v-if="detail.evidence.length" class="evidence-list">
            <EvidenceCard v-for="item in detail.evidence" :key="item.id" :evidence="item" />
          </div>
          <p v-else class="section-empty">{{ zhCN.published.detail.noEvidence }}</p>
        </div>

        <div>
          <div class="section-heading">
            <div>
              <p class="eyebrow">ACTIVITY</p>
              <h2>{{ zhCN.published.detail.activities }}</h2>
            </div>
          </div>
          <div v-if="detail.activities.length" class="activity-table-wrap">
            <table>
              <thead>
                <tr><th>Compound</th><th>Metric</th><th>Value</th><th>Status</th></tr>
              </thead>
              <tbody>
                <tr v-for="activity in detail.activities" :key="activity.id">
                  <td>{{ compoundLabels.get(activity.compound_id) || "—" }}</td>
                  <td>{{ activity.metric || "—" }}</td>
                  <td><strong>{{ activity.qualifier || "" }} {{ activity.value || "—" }} {{ activity.unit || "" }}</strong></td>
                  <td><span>{{ activity.state || "—" }}</span></td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="section-empty">{{ zhCN.published.detail.noActivities }}</p>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.detail-page { max-width: 1450px; margin: auto; padding: clamp(28px, 5vw, 58px); }
.back-link { display: inline-flex; margin-bottom: 24px; color: var(--forest-750); font-size: .76rem; font-weight: 700; text-decoration: none; }
.back-link:hover { text-decoration: underline; }
.paper-hero { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 40px; padding: clamp(26px, 4vw, 44px); border: 1px solid #cedbd3; border-radius: var(--radius-lg); background: linear-gradient(145deg, white 58%, var(--forest-100)); box-shadow: var(--shadow-sm); }
.paper-identifiers { display: flex; flex-wrap: wrap; gap: 10px 22px; color: var(--ink-500); font-size: .7rem; }
.paper-identifiers code { color: var(--ink-650); user-select: all; }
.paper-hero h1 { max-width: 900px; margin: 22px 0 26px; color: var(--ink-950); font: 600 clamp(2rem, 3.2vw, 3.4rem)/1.2 Georgia, "Noto Serif SC Variable", serif; letter-spacing: -.025em; }
.hero-tags { display: flex; flex-wrap: wrap; gap: 9px; }
.hero-tags span { padding: 7px 10px; border: 1px solid var(--line); border-radius: 999px; color: var(--ink-650); background: rgba(255,255,255,.75); font-size: .7rem; }
.release-card { align-self: start; padding: 20px; border: 1px solid #d8c89f; border-radius: 13px; background: rgba(255,254,249,.9); }
.release-card span, .release-card strong, .release-card code, .release-card small { display: block; }
.release-card span { color: var(--gold-700); font-size: .63rem; font-weight: 800; letter-spacing: .09em; }
.release-card strong { margin-top: 9px; color: var(--ink-950); font: 600 1rem/1.4 Georgia, "Noto Serif SC Variable", serif; }
.release-card code { margin-top: 9px; color: var(--ink-650); font-size: .65rem; }
.release-card small { margin-top: 14px; color: var(--ink-500); font-size: .65rem; line-height: 1.5; }
.content-section { margin-top: 42px; }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 20px; margin-bottom: 15px; }
.section-heading .eyebrow { margin-bottom: 6px; }
.section-heading h2 { margin: 0; color: var(--ink-950); font: 600 1.45rem/1.3 Georgia, "Noto Serif SC Variable", serif; }
.section-heading > span { color: var(--ink-500); font-size: .68rem; }
.structure-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 14px; }
.structure-grid article { padding: 18px; border: 1px solid var(--line); border-radius: var(--radius-md); background: white; box-shadow: var(--shadow-sm); }
.structure-label { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.structure-label span { color: var(--forest-750); font-size: .68rem; font-weight: 760; }
.structure-label strong { color: var(--ink-950); }
.structure-grid small, .structure-grid code { display: block; }
.structure-grid small { margin-top: 26px; color: var(--ink-500); font-size: .62rem; }
.structure-grid code { min-height: 68px; margin-top: 9px; padding: 15px; border: 1px solid #eef1ef; border-radius: 9px; color: var(--ink-800); background: #fbfcfb; font-size: .76rem; line-height: 1.6; overflow-wrap: anywhere; user-select: all; }
.split-section { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 28px; }
.evidence-list { display: grid; gap: 12px; }
.activity-table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: var(--radius-md); background: white; }
table { width: 100%; border-collapse: collapse; font-size: .74rem; }
th, td { padding: 14px 15px; border-bottom: 1px solid #edf0ee; text-align: left; }
th { color: var(--ink-500); background: #fafbf9; font-size: .64rem; letter-spacing: .04em; }
td { color: var(--ink-650); }
td strong { color: var(--ink-950); white-space: nowrap; }
td span { padding: 4px 7px; border-radius: 999px; color: var(--forest-750); background: var(--forest-100); font-size: .63rem; }
tbody tr:last-child td { border-bottom: 0; }
.section-empty { margin: 0; padding: 28px; border: 1px dashed var(--line-strong); border-radius: var(--radius-md); color: var(--ink-500); background: #fafbf9; font-size: .78rem; text-align: center; }
.page-state { display: grid; min-height: 360px; place-items: center; align-content: center; padding: 44px; border: 1px solid var(--line); border-radius: var(--radius-lg); background: white; text-align: center; }
.page-state h1 { margin: 15px 0 0; color: var(--ink-950); font: 600 1.55rem/1.3 Georgia, "Noto Serif SC Variable", serif; }
.page-state p { max-width: 540px; margin: 11px 0 0; color: var(--ink-650); line-height: 1.7; }
.page-state small { margin-top: 12px; color: var(--ink-500); }
.state-symbol { display: grid; min-width: 42px; height: 42px; padding: 0 10px; place-items: center; border-radius: 50%; color: var(--gold-700); background: var(--gold-100); font-size: .72rem; font-weight: 800; }
.state-symbol.is-error { color: var(--danger); background: var(--danger-soft); }
.state-spinner { width: 28px; height: 28px; border: 3px solid var(--forest-100); border-top-color: var(--forest-750); border-radius: 50%; animation: spin .8s linear infinite; }
.button-secondary { min-height: 40px; margin-top: 20px; padding: 8px 15px; border: 1px solid var(--forest-750); border-radius: var(--radius-sm); color: var(--forest-750); background: white; font-weight: 700; cursor: pointer; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 920px) { .paper-hero { grid-template-columns: 1fr; } .split-section { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { .state-spinner { animation: none; } }
</style>

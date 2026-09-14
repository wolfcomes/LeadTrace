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
import ReleaseVerificationBadge from "./ReleaseVerificationBadge.vue";


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
  <div class="published-page detail-page detail-layout" data-paper-detail>
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
          <ReleaseVerificationBadge :status="detail.release.verification_status" />
          <code>{{ detail.release.key }}</code>
          <small>{{ zhCN.published.detail.publishedAt }} · {{ formatDate(detail.release.published_at) }}</small>
        </aside>
      </header>

      <section class="content-section panel quality-section">
        <div class="section-heading">
          <div>
            <p class="eyebrow">QUALITY SIGNALS</p>
            <h2>{{ zhCN.published.detail.quality }}</h2>
          </div>
        </div>
        <QualitySummary :summary="detail.quality_summary" />
      </section>

      <section class="content-section panel">
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

      <section class="content-section panel">
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

      <section class="content-section panel split-section">
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
            <table class="data-table">
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

<script setup lang="ts">
import { ref, watch } from "vue";
import { useRoute, useRouter, type LocationQueryRaw } from "vue-router";

import { ApiError } from "../api/client";
import { fetchPapers, type PaperQuery } from "../api/published";
import type { PaperListResponse } from "../api/schema";
import { zhCN } from "../i18n/zh-CN";


type ViewState = "loading" | "ready" | "empty-release" | "error";

const route = useRoute();
const router = useRouter();
const state = ref<ViewState>("loading");
const response = ref<PaperListResponse | null>(null);
const requestId = ref<string | undefined>();
const search = ref("");
const doi = ref("");
const target = ref("");
const hasLineage = ref("");
const relationStatus = ref("");
const structureState = ref("");
const reviewStatus = ref("");
const sort = ref<PaperQuery["sort"]>("manifest");
let loadSequence = 0;

function queryValue(name: string): string {
  const value = route.query[name];
  return typeof value === "string" ? value : "";
}

function pageFromQuery(): number {
  const parsed = Number.parseInt(queryValue("page"), 10);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 1;
}

function restoreFormFromRoute(): void {
  search.value = queryValue("search");
  doi.value = queryValue("doi");
  target.value = queryValue("target");
  hasLineage.value = queryValue("has_lineage");
  relationStatus.value = queryValue("relation_status");
  structureState.value = queryValue("structure_state");
  reviewStatus.value = queryValue("review_status");
  const requestedSort = queryValue("sort");
  sort.value = ["manifest", "paper_id", "-paper_id", "title", "-title"].includes(requestedSort)
    ? requestedSort as PaperQuery["sort"]
    : "manifest";
}

function currentQuery(): PaperQuery {
  const requestedSort = queryValue("sort");
  const normalizedSort = ["manifest", "paper_id", "-paper_id", "title", "-title"].includes(requestedSort)
    ? requestedSort as PaperQuery["sort"]
    : "manifest";
  return {
    page: pageFromQuery(),
    page_size: 20,
    search: queryValue("search") || undefined,
    doi: queryValue("doi") || undefined,
    target: queryValue("target") || undefined,
    has_lineage: ["true", "false"].includes(queryValue("has_lineage"))
      ? queryValue("has_lineage") as "true" | "false"
      : undefined,
    relation_status: queryValue("relation_status") || undefined,
    structure_state: queryValue("structure_state") || undefined,
    review_status: queryValue("review_status") || undefined,
    sort: normalizedSort,
  };
}

async function load(): Promise<void> {
  const sequence = ++loadSequence;
  restoreFormFromRoute();
  state.value = "loading";
  requestId.value = undefined;
  try {
    const payload = await fetchPapers(currentQuery());
    if (sequence !== loadSequence) return;
    response.value = payload;
    state.value = "ready";
  } catch (error) {
    if (sequence !== loadSequence) return;
    response.value = null;
    if (error instanceof ApiError) {
      requestId.value = error.requestId;
      state.value = error.code === "CURRENT_RELEASE_NOT_FOUND" ? "empty-release" : "error";
    } else {
      state.value = "error";
    }
  }
}

function formQuery(page = 1): LocationQueryRaw {
  const query: LocationQueryRaw = { page: String(page) };
  const values = {
    search: search.value.trim(),
    doi: doi.value.trim(),
    target: target.value.trim(),
    has_lineage: hasLineage.value,
    relation_status: relationStatus.value,
    structure_state: structureState.value,
    review_status: reviewStatus.value,
    sort: sort.value === "manifest" ? "" : sort.value,
  };
  for (const [name, value] of Object.entries(values)) {
    if (value) query[name] = value;
  }
  return query;
}

async function applyFilters(): Promise<void> {
  await router.replace({ name: route.name ?? undefined, query: formQuery(1) });
}

async function resetFilters(): Promise<void> {
  search.value = "";
  doi.value = "";
  target.value = "";
  hasLineage.value = "";
  relationStatus.value = "";
  structureState.value = "";
  reviewStatus.value = "";
  sort.value = "manifest";
  await router.replace({ name: route.name ?? undefined, query: { page: "1" } });
}

async function goToPage(page: number): Promise<void> {
  await router.replace({ name: route.name ?? undefined, query: { ...route.query, page: String(page) } });
}

watch(() => route.fullPath, load, { immediate: true });
</script>

<template>
  <div class="published-page library-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">{{ zhCN.published.library.eyebrow }}</p>
        <h1>{{ zhCN.published.library.title }}</h1>
        <p>{{ zhCN.published.library.description }}</p>
      </div>
      <div v-if="response" class="release-chip">
        <span>{{ response.release.title }}</span>
        <code>{{ response.release.key }}</code>
      </div>
    </header>

    <form class="filter-panel" data-filter-form @submit.prevent="applyFilters">
      <div class="filter-field search-field">
        <label for="paper-search">{{ zhCN.published.library.search }}</label>
        <input id="paper-search" v-model="search" type="search" :placeholder="zhCN.published.library.searchPlaceholder">
      </div>
      <div class="filter-field">
        <label for="paper-doi">{{ zhCN.published.library.doi }}</label>
        <input id="paper-doi" v-model="doi" type="text" placeholder="10.xxxx/…">
      </div>
      <div class="filter-field">
        <label for="paper-target">{{ zhCN.published.library.target }}</label>
        <input id="paper-target" v-model="target" type="text" placeholder="Kinase A">
      </div>
      <div class="filter-field">
        <label for="paper-lineage">{{ zhCN.published.library.lineage }}</label>
        <select id="paper-lineage" v-model="hasLineage">
          <option value="">{{ zhCN.published.library.any }}</option>
          <option value="true">{{ zhCN.published.library.hasLineage }}</option>
          <option value="false">{{ zhCN.published.library.noLineage }}</option>
        </select>
      </div>
      <div class="filter-field">
        <label for="paper-relation">{{ zhCN.published.library.relation }}</label>
        <select id="paper-relation" v-model="relationStatus">
          <option value="">{{ zhCN.published.library.any }}</option>
          <option value="text_explicit">text_explicit</option>
          <option value="unresolved">unresolved</option>
          <option value="invalid">invalid</option>
        </select>
      </div>
      <div class="filter-field">
        <label for="paper-structure">{{ zhCN.published.library.structure }}</label>
        <select id="paper-structure" v-model="structureState">
          <option value="">{{ zhCN.published.library.any }}</option>
          <option value="structure_confirmed">structure_confirmed</option>
          <option value="structure_pending">structure_pending</option>
          <option value="source_mismatch">source_mismatch</option>
        </select>
      </div>
      <div class="filter-field">
        <label for="paper-review">{{ zhCN.published.library.review }}</label>
        <select id="paper-review" v-model="reviewStatus">
          <option value="">{{ zhCN.published.library.any }}</option>
          <option value="unreviewed">unreviewed</option>
          <option value="reviewed">reviewed</option>
          <option value="approved">approved</option>
        </select>
      </div>
      <div class="filter-field">
        <label for="paper-sort">{{ zhCN.published.library.sort }}</label>
        <select id="paper-sort" v-model="sort">
          <option value="manifest">{{ zhCN.published.library.manifest }}</option>
          <option value="paper_id">{{ zhCN.published.library.paperIdAscending }}</option>
          <option value="-paper_id">{{ zhCN.published.library.paperIdDescending }}</option>
          <option value="title">{{ zhCN.published.library.titleAscending }}</option>
          <option value="-title">{{ zhCN.published.library.titleDescending }}</option>
        </select>
      </div>
      <div class="filter-actions">
        <button class="button-primary" type="submit">{{ zhCN.published.library.apply }}</button>
        <button class="button-secondary" type="button" @click="resetFilters">{{ zhCN.published.library.reset }}</button>
      </div>
    </form>

    <section v-if="state === 'loading'" class="page-state" aria-live="polite">
      <span class="state-spinner" aria-hidden="true"></span>
      <p>{{ zhCN.published.states.loading }}</p>
    </section>

    <section v-else-if="state === 'empty-release'" class="page-state" data-empty-state>
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

    <template v-else-if="response">
      <div class="result-summary">
        <strong>{{ zhCN.published.library.results(response.pagination.total_items) }}</strong>
        <span v-if="response.pagination.total_pages">{{ zhCN.published.library.page(response.pagination.page, response.pagination.total_pages) }}</span>
      </div>

      <section v-if="response.items.length" class="paper-list" aria-label="已发布文献">
        <article v-for="paper in response.items" :key="paper.id" class="paper-card">
          <div class="paper-index" aria-hidden="true">LT</div>
          <div class="paper-content">
            <div class="paper-identifiers">
              <span>{{ zhCN.published.library.stableId }} <code>{{ paper.paper_key }}</code></span>
              <span v-if="paper.doi">DOI <code>{{ paper.doi }}</code></span>
            </div>
            <h2>
              <RouterLink :to="{ name: 'paper-detail', params: { paperId: paper.id } }">
                {{ paper.title }}
              </RouterLink>
            </h2>
            <div class="paper-metadata">
              <span>{{ paper.year || "—" }}</span>
              <span>{{ paper.target || "—" }}</span>
              <span class="status-pill">{{ paper.review_status || "—" }}</span>
            </div>
          </div>
          <RouterLink class="detail-link" :to="{ name: 'paper-detail', params: { paperId: paper.id } }" :aria-label="`${paper.title} · 查看详情`">→</RouterLink>
        </article>
      </section>

      <section v-else class="page-state compact">
        <span class="state-symbol" aria-hidden="true">0</span>
        <h2>{{ zhCN.published.library.emptyTitle }}</h2>
        <p>{{ zhCN.published.library.emptyBody }}</p>
      </section>

      <nav v-if="response.pagination.total_pages > 0" class="pagination" aria-label="文献分页">
        <button type="button" :disabled="response.pagination.page <= 1" @click="goToPage(response.pagination.page - 1)">{{ zhCN.published.library.previous }}</button>
        <span>{{ zhCN.published.library.page(response.pagination.page, response.pagination.total_pages) }}</span>
        <button type="button" :disabled="response.pagination.page >= response.pagination.total_pages" @click="goToPage(response.pagination.page + 1)">{{ zhCN.published.library.next }}</button>
      </nav>
    </template>
  </div>
</template>

<style scoped>
.library-page { max-width: 1450px; margin: auto; padding: clamp(30px, 5vw, 58px); }
.page-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 32px; margin-bottom: 28px; }
.page-heading h1 { margin: 0; color: var(--ink-950); font: 600 clamp(2rem, 3vw, 3rem)/1.15 Georgia, "Noto Serif SC Variable", serif; letter-spacing: -.025em; }
.page-heading > div > p:last-child { max-width: 710px; margin: 15px 0 0; color: var(--ink-650); font-size: .88rem; line-height: 1.75; }
.release-chip { max-width: 300px; padding: 13px 15px; border: 1px solid #d8c89f; border-radius: 10px; background: var(--gold-100); }
.release-chip span, .release-chip code { display: block; }
.release-chip span { color: var(--ink-800); font-size: .73rem; font-weight: 700; }
.release-chip code { margin-top: 5px; color: var(--ink-500); font-size: .62rem; }
.filter-panel { display: grid; grid-template-columns: repeat(4, minmax(150px, 1fr)); gap: 14px; padding: 20px; border: 1px solid var(--line); border-radius: var(--radius-md); background: white; box-shadow: var(--shadow-sm); }
.filter-field label { display: block; margin-bottom: 7px; color: var(--ink-650); font-size: .68rem; font-weight: 740; }
.filter-field input, .filter-field select { width: 100%; min-height: 42px; padding: 8px 10px; border: 1px solid var(--line-strong); border-radius: 8px; color: var(--ink-950); background: #fbfcfb; font-size: .78rem; }
.filter-field input:focus, .filter-field select:focus { border-color: var(--forest-750); box-shadow: 0 0 0 3px rgba(29,90,71,.08); outline: 0; }
.search-field { grid-column: span 2; }
.filter-actions { display: flex; align-items: end; gap: 9px; }
.filter-actions button { min-height: 42px; padding: 8px 14px; }
.button-secondary { border: 1px solid var(--line-strong); border-radius: 8px; color: var(--ink-650); background: white; font-weight: 700; cursor: pointer; }
.result-summary { display: flex; align-items: center; justify-content: space-between; margin: 30px 2px 13px; color: var(--ink-650); font-size: .75rem; }
.result-summary strong { color: var(--ink-800); }
.paper-list { display: grid; gap: 10px; }
.paper-card { display: grid; grid-template-columns: 44px minmax(0, 1fr) 38px; align-items: center; gap: 18px; padding: 20px; border: 1px solid var(--line); border-radius: 12px; background: white; box-shadow: var(--shadow-sm); transition: border-color .15s ease, box-shadow .15s ease, transform .15s ease; }
.paper-card:hover { border-color: #b8c8bf; box-shadow: 0 10px 30px rgba(18,42,33,.07); transform: translateY(-1px); }
.paper-index { display: grid; width: 42px; height: 42px; place-items: center; border: 1px solid #ccd8d1; border-radius: 10px; color: var(--forest-750); background: var(--forest-100); font: 700 .65rem/1 Georgia, serif; }
.paper-identifiers { display: flex; flex-wrap: wrap; gap: 8px 18px; color: var(--ink-500); font-size: .65rem; }
.paper-identifiers code { color: var(--ink-650); user-select: all; }
.paper-card h2 { margin: 9px 0 10px; font: 600 1rem/1.45 Georgia, "Noto Serif SC Variable", serif; }
.paper-card h2 a { color: var(--ink-950); text-decoration: none; }
.paper-card h2 a:hover { color: var(--forest-750); }
.paper-metadata { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 18px; color: var(--ink-500); font-size: .7rem; }
.status-pill { padding: 4px 8px; border-radius: 999px; color: var(--gold-700); background: var(--gold-100); }
.detail-link { display: grid; width: 34px; height: 34px; place-items: center; border: 1px solid var(--line); border-radius: 50%; color: var(--forest-750); text-decoration: none; }
.detail-link:hover { color: white; background: var(--forest-750); }
.pagination { display: flex; align-items: center; justify-content: center; gap: 18px; padding: 28px 0 0; color: var(--ink-650); font-size: .75rem; }
.pagination button { min-height: 38px; padding: 7px 13px; border: 1px solid var(--line-strong); border-radius: 8px; color: var(--forest-750); background: white; font-weight: 700; cursor: pointer; }
.pagination button:disabled { color: var(--ink-500); cursor: not-allowed; opacity: .5; }
.page-state { display: grid; min-height: 270px; place-items: center; align-content: center; margin: 28px 0 0; padding: 38px; border: 1px solid var(--line); border-radius: var(--radius-md); background: white; text-align: center; }
.page-state.compact { min-height: 220px; }
.page-state h2 { margin: 14px 0 0; color: var(--ink-950); font: 600 1.35rem/1.3 Georgia, "Noto Serif SC Variable", serif; }
.page-state p { max-width: 530px; margin: 10px 0 0; color: var(--ink-650); line-height: 1.65; }
.page-state small { margin-top: 12px; color: var(--ink-500); }
.page-state .button-secondary { margin-top: 18px; padding: 8px 14px; }
.state-symbol { display: grid; width: 40px; height: 40px; place-items: center; border-radius: 50%; color: var(--gold-700); background: var(--gold-100); font-weight: 800; }
.state-symbol.is-error { color: var(--danger); background: var(--danger-soft); }
.state-spinner { width: 28px; height: 28px; border: 3px solid var(--forest-100); border-top-color: var(--forest-750); border-radius: 50%; animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1100px) { .filter-panel { grid-template-columns: repeat(2, minmax(150px, 1fr)); } }
@media (max-width: 700px) { .page-heading { flex-direction: column; } .filter-panel { grid-template-columns: 1fr; } .search-field { grid-column: auto; } .paper-card { grid-template-columns: 38px minmax(0, 1fr); } .detail-link { display: none; } }
@media (prefers-reduced-motion: reduce) { .state-spinner { animation: none; } }
</style>

<script setup lang="ts">
import { ref, watch } from "vue";
import { useRoute, useRouter, type LocationQueryRaw } from "vue-router";

import { ApiError } from "../api/client";
import { fetchPapers, type PaperQuery } from "../api/published";
import type { PaperListResponse } from "../api/schema";
import { zhCN } from "../i18n/zh-CN";
import ReleaseVerificationBadge from "./ReleaseVerificationBadge.vue";


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
    <header class="page-heading page-heading--editorial">
      <div>
        <p class="eyebrow">{{ zhCN.published.library.eyebrow }}</p>
        <h1>{{ zhCN.published.library.title }}</h1>
        <p>{{ zhCN.published.library.description }}</p>
      </div>
      <div v-if="response" class="release-chip">
        <span>{{ response.release.title }}</span>
        <ReleaseVerificationBadge :status="response.release.verification_status" />
        <code>{{ response.release.key }}</code>
      </div>
    </header>

    <form class="filter-panel filter-toolbar" data-filter-form @submit.prevent="applyFilters">
      <div class="filter-field form-field search-field">
        <label for="paper-search">{{ zhCN.published.library.search }}</label>
        <input id="paper-search" v-model="search" type="search" :placeholder="zhCN.published.library.searchPlaceholder">
      </div>
      <div class="filter-field form-field">
        <label for="paper-doi">{{ zhCN.published.library.doi }}</label>
        <input id="paper-doi" v-model="doi" type="text" placeholder="10.xxxx/…">
      </div>
      <div class="filter-field form-field">
        <label for="paper-target">{{ zhCN.published.library.target }}</label>
        <input id="paper-target" v-model="target" type="text" placeholder="Kinase A">
      </div>
      <div class="filter-field form-field">
        <label for="paper-lineage">{{ zhCN.published.library.lineage }}</label>
        <select id="paper-lineage" v-model="hasLineage">
          <option value="">{{ zhCN.published.library.any }}</option>
          <option value="true">{{ zhCN.published.library.hasLineage }}</option>
          <option value="false">{{ zhCN.published.library.noLineage }}</option>
        </select>
      </div>
      <div class="filter-field form-field">
        <label for="paper-relation">{{ zhCN.published.library.relation }}</label>
        <select id="paper-relation" v-model="relationStatus">
          <option value="">{{ zhCN.published.library.any }}</option>
          <option value="text_explicit">text_explicit</option>
          <option value="unresolved">unresolved</option>
          <option value="invalid">invalid</option>
        </select>
      </div>
      <div class="filter-field form-field">
        <label for="paper-structure">{{ zhCN.published.library.structure }}</label>
        <select id="paper-structure" v-model="structureState">
          <option value="">{{ zhCN.published.library.any }}</option>
          <option value="structure_confirmed">structure_confirmed</option>
          <option value="structure_pending">structure_pending</option>
          <option value="source_mismatch">source_mismatch</option>
        </select>
      </div>
      <div class="filter-field form-field">
        <label for="paper-review">{{ zhCN.published.library.review }}</label>
        <select id="paper-review" v-model="reviewStatus">
          <option value="">{{ zhCN.published.library.any }}</option>
          <option value="unreviewed">unreviewed</option>
          <option value="reviewed">reviewed</option>
          <option value="approved">approved</option>
        </select>
      </div>
      <div class="filter-field form-field">
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

      <section v-if="response.items.length" class="paper-list panel" data-paper-list aria-label="已发布文献">
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
              <span class="status-chip is-pending">{{ paper.review_status || "—" }}</span>
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
        <button class="button-secondary" type="button" :disabled="response.pagination.page <= 1" @click="goToPage(response.pagination.page - 1)">{{ zhCN.published.library.previous }}</button>
        <span>{{ zhCN.published.library.page(response.pagination.page, response.pagination.total_pages) }}</span>
        <button class="button-secondary" type="button" :disabled="response.pagination.page >= response.pagination.total_pages" @click="goToPage(response.pagination.page + 1)">{{ zhCN.published.library.next }}</button>
      </nav>
    </template>
  </div>
</template>

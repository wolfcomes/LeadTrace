<script setup lang="ts">
import { ref, watch } from "vue";
import { useRoute, useRouter, type LocationQueryRaw } from "vue-router";

import { ApiError } from "../api/client";
import {
  fetchAdminPapers,
  type AdminPaperList,
} from "./api";
import { adminPaperWorkflowLabel, adminPaperWorkflowStates } from "./paperWorkflow";


type ViewState = "loading" | "ready" | "error";

const route = useRoute();
const router = useRouter();
const state = ref<ViewState>("loading");
const payload = ref<AdminPaperList | null>(null);
const requestId = ref<string>();
const search = ref("");
const doi = ref("");
const workflowState = ref("");
const publicationStatus = ref("");
let loadSequence = 0;

function queryValue(name: string): string {
  const value = route.query[name];
  return typeof value === "string" ? value : "";
}

function pageFromRoute(): number {
  const value = Number.parseInt(queryValue("page"), 10);
  return Number.isInteger(value) && value > 0 ? value : 1;
}

function restoreFilters(): void {
  search.value = queryValue("search");
  doi.value = queryValue("doi");
  workflowState.value = queryValue("workflow_state");
  publicationStatus.value = queryValue("publication_status");
}

function requestParams(): Record<string, string> {
  const params: Record<string, string> = {
    page: String(pageFromRoute()),
    page_size: "20",
  };
  for (const key of [
    "candidate_id",
    "search",
    "doi",
    "workflow_state",
    "publication_status",
    "assignee_id",
  ]) {
    const value = queryValue(key);
    if (value) params[key] = value;
  }
  return params;
}

async function load(): Promise<void> {
  const sequence = ++loadSequence;
  restoreFilters();
  state.value = "loading";
  requestId.value = undefined;
  try {
    const response = await fetchAdminPapers(requestParams());
    if (sequence !== loadSequence) return;
    payload.value = response;
    state.value = "ready";
  } catch (error) {
    if (sequence !== loadSequence) return;
    payload.value = null;
    requestId.value = error instanceof ApiError ? error.requestId : undefined;
    state.value = "error";
  }
}

function filterQuery(page = 1): LocationQueryRaw {
  const query: LocationQueryRaw = { page: String(page) };
  const candidateId = queryValue("candidate_id");
  if (candidateId) query.candidate_id = candidateId;
  const values = {
    search: search.value.trim(),
    doi: doi.value.trim(),
    workflow_state: workflowState.value,
    publication_status: publicationStatus.value,
  };
  for (const [key, value] of Object.entries(values)) {
    if (value) query[key] = value;
  }
  return query;
}

async function applyFilters(): Promise<void> {
  await router.replace({ name: "admin-papers", query: filterQuery(1) });
}

async function resetFilters(): Promise<void> {
  search.value = "";
  doi.value = "";
  workflowState.value = "";
  publicationStatus.value = "";
  await router.replace({ name: "admin-papers", query: filterQuery(1) });
}

async function goToPage(page: number): Promise<void> {
  await router.replace({ name: "admin-papers", query: { ...route.query, page: String(page) } });
}

watch(() => route.fullPath, load, { immediate: true });
</script>

<template>
  <div class="catalog-page admin-page review-workspace">
    <header class="page-heading">
      <div>
        <p class="eyebrow">ADMIN PAPER CATALOG</p>
        <h1>文章目录</h1>
        <p>查看数据库中的全部文章、AI 提取质量、分配进度和人工核验状态。</p>
      </div>
      <div v-if="payload" class="source-summary panel">
        <span>{{ payload.source.title }}</span>
        <strong class="status-chip" :data-verification="payload.source.verification_status">
          {{ payload.source.verification_status === "human_verified" ? "已人工核验" : "未验证" }}
        </strong>
        <small class="status-chip" :data-status="payload.source.publication_status">{{ payload.source.publication_status === "published" ? "已发布" : "未发布" }}</small>
      </div>
    </header>

    <section v-if="payload" class="status-overview admin-metric-grid" aria-label="文章流程状态统计">
      <button
        v-for="entry in adminPaperWorkflowStates"
        :key="entry.value"
        type="button"
        :class="{ active: workflowState === entry.value }"
        :data-workflow-count="entry.value"
        @click="workflowState = workflowState === entry.value ? '' : entry.value; applyFilters()"
      >
        <span>{{ entry.short }}</span>
        <strong>{{ (payload.status_counts[entry.value] ?? 0).toLocaleString("zh-CN") }}</strong>
        <small>{{ entry.label }}</small>
      </button>
    </section>

    <form class="filter-panel filter-toolbar" data-admin-paper-filters @submit.prevent="applyFilters">
      <label class="wide form-field">搜索文章<input v-model="search" type="search" placeholder="标题、DOI、文章编号或靶点"></label>
      <label class="form-field">DOI<input v-model="doi" type="text" placeholder="10.xxxx/…"></label>
      <label class="form-field">流程状态<select id="admin-paper-workflow" v-model="workflowState">
        <option value="">全部状态</option>
        <option v-for="entry in adminPaperWorkflowStates" :key="entry.value" :value="entry.value">{{ entry.label }}</option>
      </select></label>
      <label class="form-field">发布状态<select v-model="publicationStatus">
        <option value="">全部</option>
        <option value="unpublished">未发布</option>
        <option value="published">已发布</option>
      </select></label>
      <div class="filter-actions">
        <button class="button-primary" type="submit">应用筛选</button>
        <button class="button-secondary" type="button" @click="resetFilters">清除</button>
      </div>
    </form>

    <section v-if="state === 'loading'" class="page-state" aria-live="polite">
      <span class="state-spinner" aria-hidden="true"></span><p>正在读取数据库文章…</p>
    </section>
    <section v-else-if="state === 'error'" class="page-state error" role="alert">
      <span>!</span><h2>暂时无法读取文章目录</h2>
      <p>请稍后重试；如问题持续，请将请求编号提供给管理员。</p>
      <small v-if="requestId">请求编号 · {{ requestId }}</small>
      <button class="button-secondary" type="button" @click="load">重新加载</button>
    </section>

    <template v-else-if="payload">
      <div class="result-heading">
        <strong>共 {{ payload.pagination.total_items.toLocaleString("zh-CN") }} 篇</strong>
        <span v-if="payload.pagination.total_pages">第 {{ payload.pagination.page }} / {{ payload.pagination.total_pages }} 页</span>
      </div>
      <div v-if="payload.items.length" class="table-wrap admin-panel">
        <table class="data-table">
          <thead><tr><th>文章</th><th>流程状态</th><th>数据库内容</th><th>分配</th><th>可见性</th><th><span class="sr-only">操作</span></th></tr></thead>
          <tbody>
            <tr v-for="paper in payload.items" :key="paper.id" data-admin-paper>
              <th scope="row">
                <code>{{ paper.paper_key }}</code>
                <RouterLink :to="{ name: 'admin-paper-detail', params: { paperId: paper.id }, query: route.query.candidate_id ? { candidate_id: route.query.candidate_id } : {} }">{{ paper.title }}</RouterLink>
                <small>{{ paper.doi || "无 DOI" }} · {{ paper.year || "年份未知" }}<template v-if="paper.target"> · {{ paper.target }}</template></small>
              </th>
              <td><span class="workflow-badge status-chip" :data-state="paper.workflow_state">{{ adminPaperWorkflowLabel(paper.workflow_state) }}</span></td>
              <td class="quality-cell">
                <span>{{ paper.quality.compounds }} 分子</span>
                <span>{{ paper.quality.confirmed_structures }}/{{ paper.quality.structures }} 结构确认</span>
                <span>{{ paper.quality.evidence }} 证据</span>
              </td>
              <td>
                <template v-if="paper.task"><strong class="assignee">{{ paper.task.assignee_display_name }}</strong><small>{{ paper.task.status }}</small></template>
                <span v-else class="muted">未分配</span>
              </td>
              <td><span class="visibility status-chip" :data-status="paper.publication_status">{{ paper.publication_status === "published" ? "已发布" : "未发布" }}</span><small v-if="paper.verification_status !== 'human_verified'" class="unverified status-chip is-warning">未验证</small></td>
              <td class="actions table-actions"><RouterLink class="detail-link button-secondary compact-action" :to="{ name: 'admin-paper-detail', params: { paperId: paper.id }, query: route.query.candidate_id ? { candidate_id: route.query.candidate_id } : {} }">查看 / 修改 →</RouterLink></td>
            </tr>
          </tbody>
        </table>
      </div>
      <section v-else class="page-state compact"><span>0</span><h2>没有符合条件的文章</h2><p>请调整搜索词或筛选条件。</p></section>
      <nav v-if="payload.pagination.total_pages > 0" class="pagination" aria-label="文章目录分页">
        <button class="button-secondary" type="button" :disabled="payload.pagination.page <= 1" @click="goToPage(payload.pagination.page - 1)">上一页</button>
        <span>第 {{ payload.pagination.page }} / {{ payload.pagination.total_pages }} 页</span>
        <button class="button-secondary" type="button" :disabled="payload.pagination.page >= payload.pagination.total_pages" @click="goToPage(payload.pagination.page + 1)">下一页</button>
      </nav>
    </template>
  </div>
</template>

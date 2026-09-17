<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { ApiError } from "../api/client";
import { listAdminPapers } from "../v2/api";
import type { AssignmentResponse, PaperCatalogPage, PaperCatalogRow } from "../v2/types";
import AiPrefillStatus from "./AiPrefillStatus.vue";
import ReviewerAssignmentDialog from "./ReviewerAssignmentDialog.vue";


type ViewState = "loading" | "ready" | "error";

const PAGE_SIZE = 20;
const route = useRoute();
const router = useRouter();
const state = ref<ViewState>("loading");
const payload = ref<PaperCatalogPage>();
const search = ref("");
const requestId = ref<string>();
const assignmentPaper = ref<PaperCatalogRow>();
let loadSequence = 0;

const currentPage = computed(() => payload.value
  ? Math.floor(payload.value.offset / payload.value.limit) + 1
  : pageFromRoute());
const totalPages = computed(() => payload.value
  ? Math.ceil(payload.value.total / payload.value.limit)
  : 0);

function queryValue(name: string): string {
  const value = route.query[name];
  return typeof value === "string" ? value : "";
}

function pageFromRoute(): number {
  const page = Number.parseInt(queryValue("page"), 10);
  return Number.isInteger(page) && page > 0 ? page : 1;
}

async function load(): Promise<void> {
  const sequence = ++loadSequence;
  const page = pageFromRoute();
  search.value = queryValue("search");
  state.value = "loading";
  requestId.value = undefined;
  try {
    const result = await listAdminPapers({
      limit: PAGE_SIZE,
      offset: (page - 1) * PAGE_SIZE,
      search: search.value || undefined,
    });
    if (sequence !== loadSequence) return;
    payload.value = result;
    state.value = "ready";
  } catch (error) {
    if (sequence !== loadSequence) return;
    payload.value = undefined;
    requestId.value = error instanceof ApiError ? error.requestId : undefined;
    state.value = "error";
  }
}

async function applySearch(): Promise<void> {
  const value = search.value.trim();
  await router.replace({
    name: "admin-papers",
    query: value ? { page: "1", search: value } : { page: "1" },
  });
}

async function clearSearch(): Promise<void> {
  search.value = "";
  await router.replace({ name: "admin-papers", query: { page: "1" } });
}

async function goToPage(page: number): Promise<void> {
  await router.replace({
    name: "admin-papers",
    query: { ...route.query, page: String(page) },
  });
}

function sourceLabel(paper: PaperCatalogRow): string {
  const labels = {
    registered: "PDF 已登记",
    verified: "PDF 已验证",
    missing: "PDF 缺失",
    corrupt: "PDF 已损坏",
  } as const;
  return labels[paper.source.integrity_state];
}

function sourceHealthy(paper: PaperCatalogRow): boolean {
  return paper.catalog_state !== "source_error" && paper.source.integrity_state === "verified";
}

function canAssign(paper: PaperCatalogRow): boolean {
  return sourceHealthy(paper) && (!paper.review || paper.review.task_status === "approved");
}

function assignmentLabel(paper: PaperCatalogRow): string {
  if (!sourceHealthy(paper)) return "Source 异常";
  if (!paper.review) return "分配 Reviewer";
  return paper.review.task_status === "approved" ? "再次分配" : "已分配";
}

function submissionLabel(paper: PaperCatalogRow): string {
  const submissionState = paper.review?.submission_state ?? "not_submitted";
  return {
    not_submitted: "未提交",
    submitted: "待 Admin 审批",
    changes_requested: "已退回修改",
    approved: "已批准",
  }[submissionState];
}

function onAssigned(result: AssignmentResponse, reviewerName: string): void {
  if (!payload.value) return;
  payload.value = {
    ...payload.value,
    items: payload.value.items.map((paper) => paper.id === result.paper_id
      ? {
        ...paper,
        review: {
          review_task_id: result.review_task_id,
          workspace_id: result.workspace_id,
          assigned_reviewer_id: result.assigned_reviewer_id,
          assignee_display_name: reviewerName,
          task_status: result.task_status,
          workspace_state: result.workspace_state,
          sections_resolved: result.sections.filter((section) => section.state !== "pending").length,
          sections_total: result.sections.length,
          submission_state: "not_submitted",
        },
        ai_prefill: {
          run: null,
          can_start: true,
          blocked_reason: null,
        },
      }
      : paper),
  };
  assignmentPaper.value = undefined;
}

watch(() => route.fullPath, load, { immediate: true });
</script>

<template>
  <div class="catalog-page admin-page review-workspace">
    <header class="page-heading">
      <div>
        <p class="eyebrow">ADMIN · PAPER CATALOG</p>
        <h1>文章目录</h1>
        <p>管理试点文章与 Source PDF 的一一映射，并将文章直接分配给 Reviewer。</p>
      </div>
      <div v-if="payload" class="catalog-total" aria-label="目录文章数">
        <strong>{{ payload.total }}</strong><span>篇文章</span>
      </div>
    </header>

    <form class="catalog-toolbar filter-toolbar" data-admin-paper-filters @submit.prevent="applySearch">
      <label class="form-field catalog-search">
        搜索目录
        <input v-model="search" type="search" placeholder="标题、文章 ID、期刊或 DOI">
      </label>
      <div class="filter-actions">
        <button class="button-primary" type="submit">搜索</button>
        <button class="button-secondary" type="button" @click="clearSearch">清除</button>
      </div>
    </form>

    <section v-if="state === 'loading'" class="page-state" aria-live="polite">
      <span class="state-spinner" aria-hidden="true"></span><p>正在读取文章目录…</p>
    </section>
    <section v-else-if="state === 'error'" class="page-state error" role="alert">
      <span class="state-symbol is-error">!</span><h2>暂时无法读取文章目录</h2>
      <p>请稍后重试。</p><small v-if="requestId">请求编号 · {{ requestId }}</small>
      <button class="button-secondary" type="button" @click="load">重新加载</button>
    </section>

    <template v-else-if="payload">
      <div class="result-heading">
        <strong>共 {{ payload.total }} 篇</strong>
        <span v-if="totalPages">第 {{ currentPage }} / {{ totalPages }} 页</span>
      </div>
      <section v-if="payload.items.length" class="admin-panel table-wrap" data-paper-catalog>
        <table class="data-table catalog-table">
          <thead>
            <tr>
              <th>文章</th><th>期刊信息</th><th>Source PDF</th><th>Reviewer</th>
              <th>区段进度</th><th>提交状态</th><th>AI 预填</th><th><span class="sr-only">操作</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="paper in payload.items" :key="paper.id" :data-paper-id="paper.id">
              <th scope="row" data-label="文章">
                <code>{{ paper.paper_key }}</code>
                <RouterLink
                  data-paper-detail
                  :to="{ name: 'admin-paper-detail', params: { paperId: paper.id }, query: route.query }"
                >{{ paper.title }}</RouterLink>
                <small>{{ paper.doi || "无 DOI" }}</small>
              </th>
              <td data-label="期刊信息">
                <strong>{{ paper.journal }}</strong>
                <small>{{ paper.publication_year }} · Volume {{ paper.volume }} · Issue {{ paper.issue }}</small>
              </td>
              <td data-label="Source PDF">
                <span class="status-chip" :data-status="paper.source.integrity_state">{{ sourceLabel(paper) }}</span>
                <small>{{ paper.source.page_count }} 页</small>
              </td>
              <td data-label="Reviewer">
                <strong v-if="paper.review">{{ paper.review.assignee_display_name }}</strong>
                <span v-else class="muted">未分配</span>
              </td>
              <td data-label="区段进度">
                <strong>{{ paper.review?.sections_resolved ?? 0 }} / {{ paper.review?.sections_total ?? 6 }}</strong>
                <small>已处置</small>
              </td>
              <td data-label="提交状态">
                <span class="status-chip" :data-status="paper.review?.submission_state ?? 'not_submitted'">{{ submissionLabel(paper) }}</span>
              </td>
              <td data-label="AI 预填">
                <AiPrefillStatus :paper-id="paper.id" :status="paper.ai_prefill" compact />
              </td>
              <td class="actions table-actions" data-label="操作">
                <button
                  class="button-secondary compact-action"
                  data-assign
                  type="button"
                  :disabled="!canAssign(paper)"
                  :title="sourceHealthy(paper) ? assignmentLabel(paper) : 'Source PDF 完整性异常，不能分配'"
                  @click="assignmentPaper = paper"
                >{{ assignmentLabel(paper) }}</button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
      <section v-else class="page-state compact"><span>0</span><h2>没有匹配的文章</h2><p>请调整搜索词后重试。</p></section>
      <nav v-if="totalPages" class="pagination" aria-label="文章目录分页">
        <button class="button-secondary" data-previous-page type="button" :disabled="currentPage <= 1" @click="goToPage(currentPage - 1)">上一页</button>
        <span>第 {{ currentPage }} / {{ totalPages }} 页</span>
        <button class="button-secondary" data-next-page type="button" :disabled="currentPage >= totalPages" @click="goToPage(currentPage + 1)">下一页</button>
      </nav>
    </template>

    <ReviewerAssignmentDialog
      v-if="assignmentPaper"
      :paper="assignmentPaper"
      @close="assignmentPaper = undefined"
      @assigned="onAssigned"
    />
  </div>
</template>

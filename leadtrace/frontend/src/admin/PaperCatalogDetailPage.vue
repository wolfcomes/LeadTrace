<script setup lang="ts">
import { ref, watch } from "vue";
import { useRoute } from "vue-router";

import { ApiError } from "../api/client";
import { getAdminPaper } from "../v2/api";
import type { AssignmentResponse, PaperCatalogRow } from "../v2/types";
import ReviewerAssignmentDialog from "./ReviewerAssignmentDialog.vue";


type ViewState = "loading" | "ready" | "error" | "not-found";

const route = useRoute();
const state = ref<ViewState>("loading");
const paper = ref<PaperCatalogRow>();
const requestId = ref<string>();
const showAssignment = ref(false);
let loadSequence = 0;

function sourceHealthy(value: PaperCatalogRow): boolean {
  return value.catalog_state !== "source_error" && value.source.integrity_state === "verified";
}

function canAssign(value: PaperCatalogRow): boolean {
  return sourceHealthy(value) && (!value.review || value.review.task_status === "approved");
}

function sourceLabel(value: PaperCatalogRow): string {
  return {
    registered: "PDF 已登记",
    verified: "PDF 已验证",
    missing: "PDF 缺失",
    corrupt: "PDF 已损坏",
  }[value.source.integrity_state];
}

function submissionLabel(value: PaperCatalogRow): string {
  return {
    not_submitted: "未提交",
    submitted: "待 Admin 审批",
    changes_requested: "已退回修改",
    approved: "已批准",
  }[value.review?.submission_state ?? "not_submitted"];
}

async function load(): Promise<void> {
  const sequence = ++loadSequence;
  state.value = "loading";
  paper.value = undefined;
  requestId.value = undefined;
  try {
    const result = await getAdminPaper(String(route.params.paperId));
    if (sequence !== loadSequence) return;
    paper.value = result;
    state.value = "ready";
  } catch (error) {
    if (sequence !== loadSequence) return;
    requestId.value = error instanceof ApiError ? error.requestId : undefined;
    state.value = error instanceof ApiError && error.status === 404 ? "not-found" : "error";
  }
}

function onAssigned(result: AssignmentResponse, reviewerName: string): void {
  if (!paper.value) return;
  paper.value = {
    ...paper.value,
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
  };
  showAssignment.value = false;
}

watch(() => route.params.paperId, load, { immediate: true });
</script>

<template>
  <div class="detail-page admin-page review-workspace">
    <RouterLink class="back-link" :to="{ name: 'admin-papers', query: route.query }">← 返回文章目录</RouterLink>

    <section v-if="state === 'loading'" class="page-state"><span class="state-spinner"></span><p>正在读取文章信息…</p></section>
    <section v-else-if="state === 'not-found'" class="page-state"><span>404</span><h1>未找到文章</h1></section>
    <section v-else-if="state === 'error'" class="page-state" role="alert">
      <span class="state-symbol is-error">!</span><h1>暂时无法读取文章</h1>
      <small v-if="requestId">请求编号 · {{ requestId }}</small>
      <button class="button-secondary" type="button" @click="load">重新加载</button>
    </section>

    <template v-else-if="paper">
      <header class="paper-header page-heading">
        <div>
          <div class="identifiers"><code class="status-chip">{{ paper.paper_key }}</code><code v-if="paper.doi" class="status-chip">{{ paper.doi }}</code></div>
          <h1>{{ paper.title }}</h1>
          <p>{{ paper.journal }} · {{ paper.publication_year }} · Volume {{ paper.volume }} · Issue {{ paper.issue }}</p>
        </div>
        <span class="status-chip" :data-status="paper.source.integrity_state">{{ sourceLabel(paper) }}</span>
      </header>

      <section class="catalog-detail-grid">
        <div class="main-column">
          <section class="panel catalog-metadata">
            <div class="section-heading"><div><p class="eyebrow">BIBLIOGRAPHY</p><h2>目录基础信息</h2></div></div>
            <dl>
              <div><dt>Paper ID</dt><dd><code>{{ paper.id }}</code></dd></div>
              <div><dt>期刊</dt><dd>{{ paper.journal }}</dd></div>
              <div><dt>年份</dt><dd>{{ paper.publication_year }}</dd></div>
              <div><dt>Volume</dt><dd>{{ paper.volume }}</dd></div>
              <div><dt>Issue</dt><dd>{{ paper.issue }}</dd></div>
              <div><dt>DOI</dt><dd>{{ paper.doi || "未登记" }}</dd></div>
            </dl>
          </section>

          <section class="panel source-panel">
            <div>
              <p class="eyebrow">SOURCE PDF</p><h2>原始文献</h2>
              <p>{{ paper.source.source_key }} · {{ paper.source.page_count }} 页 · {{ paper.source.byte_size.toLocaleString("zh-CN") }} bytes</p>
            </div>
            <a class="button-secondary" data-source-pdf :href="`/api/v2/papers/${paper.id}/source-pdf`" target="_blank" rel="noopener">打开 PDF ↗</a>
          </section>
        </div>

        <aside class="review-panel panel">
          <p class="eyebrow">REVIEW WORKFLOW</p><h2>Reviewer 工作流</h2>
          <template v-if="paper.review">
            <dl class="review-summary">
              <div><dt>Reviewer</dt><dd>{{ paper.review.assignee_display_name }}</dd></div>
              <div><dt>区段进度</dt><dd>{{ paper.review.sections_resolved }} / {{ paper.review.sections_total }}</dd></div>
              <div><dt>提交状态</dt><dd>{{ submissionLabel(paper) }}</dd></div>
            </dl>
            <RouterLink
              v-if="paper.review.task_status !== 'approved'"
              class="button-primary full"
              :to="`/review/papers/${paper.id}`"
            >查看 Reviewer Workspace</RouterLink>
          </template>
          <p v-else>尚未分配。Reviewer 可从空白 Workspace 开始，不需要先运行 AI。</p>
          <p v-if="!sourceHealthy(paper)" class="inline-feedback is-error">Source PDF 完整性异常，修复前不能分配。</p>
          <button class="button-primary full" data-assign type="button" :disabled="!canAssign(paper)" @click="showAssignment = true">
            {{ paper.review?.task_status === "approved" ? "再次分配" : paper.review ? "已分配" : "分配 Reviewer" }}
          </button>
        </aside>
      </section>
    </template>

    <ReviewerAssignmentDialog
      v-if="paper && showAssignment"
      :paper="paper"
      @close="showAssignment = false"
      @assigned="onAssigned"
    />
  </div>
</template>

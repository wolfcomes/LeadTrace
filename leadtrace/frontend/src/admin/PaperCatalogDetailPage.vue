<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { ApiError } from "../api/client";
import { createReviewTask } from "../review/api";
import {
  fetchAdminPaper,
  fetchAdminUsers,
  type AdminPaperDetail,
  type AdminUser,
} from "./api";
import { adminPaperWorkflowLabel } from "./paperWorkflow";


type ViewState = "loading" | "ready" | "error" | "not-found";

const route = useRoute();
const state = ref<ViewState>("loading");
const detail = ref<AdminPaperDetail | null>(null);
const reviewers = ref<AdminUser[]>([]);
const reviewerId = ref("");
const priority = ref(50);
const busy = ref(false);
const actionError = ref<string>();
const requestId = ref<string>();
let loadSequence = 0;

const enabledReviewers = computed(() => reviewers.value.filter(
  (user) => user.role === "reviewer" && user.is_enabled,
));

const reviewEntry = computed(() => {
  if (!detail.value) return null;
  if (detail.value.review_entry) return detail.value.review_entry;
  if (detail.value.paper.changeset) return `/review/changesets/${detail.value.paper.changeset.id}`;
  if (detail.value.paper.task) return `/review/changesets?task=${detail.value.paper.task.id}`;
  return null;
});

const blockerText = computed(() => {
  switch (detail.value?.paper.modification_blocker) {
    case "baseline_must_be_published": return "必须先批准并发布 AI 提取基线，之后才能创建可追溯修改。";
    case "review_task_required": return "先分配一名核查员，再进入可追溯修改工作区。";
    case "pending_admin_approval": return "人工核验已经提交，当前等待 Admin 审批。";
    case "approved_changeset_locked": return "已批准版本保持只读；如需继续修改，请创建新的核查任务。";
    default: return "";
  }
});

async function load(): Promise<void> {
  const sequence = ++loadSequence;
  state.value = "loading";
  detail.value = null;
  requestId.value = undefined;
  actionError.value = undefined;
  const paperId = String(route.params.paperId || "");
  const candidateId = typeof route.query.candidate_id === "string" ? route.query.candidate_id : undefined;
  try {
    const [paper, users] = await Promise.all([
      fetchAdminPaper(paperId, candidateId),
      fetchAdminUsers(),
    ]);
    if (sequence !== loadSequence) return;
    detail.value = paper;
    reviewers.value = users;
    reviewerId.value = enabledReviewers.value[0]?.id ?? "";
    state.value = "ready";
  } catch (error) {
    if (sequence !== loadSequence) return;
    requestId.value = error instanceof ApiError ? error.requestId : undefined;
    state.value = error instanceof ApiError && error.status === 404 ? "not-found" : "error";
  }
}

async function assignPaper(): Promise<void> {
  if (!detail.value || !reviewerId.value || busy.value) return;
  busy.value = true;
  actionError.value = undefined;
  try {
    const task = await createReviewTask({
      paper_id: detail.value.paper.id,
      assigned_reviewer_id: reviewerId.value,
      priority: priority.value,
    });
    const reviewer = reviewers.value.find((user) => user.id === task.assigned_reviewer_id);
    detail.value.paper.task = {
      id: task.id,
      status: task.status,
      assignee_id: task.assigned_reviewer_id,
      assignee_display_name: reviewer?.display_name ?? "未知用户",
      priority: task.priority,
      version: task.version,
      updated_at: task.updated_at,
    };
    detail.value.paper.workflow_state = "ai_baseline_in_review";
    detail.value.paper.can_modify = true;
    detail.value.paper.modification_blocker = null;
    detail.value.review_entry = `/review/changesets?task=${task.id}`;
  } catch (error) {
    requestId.value = error instanceof ApiError ? error.requestId : undefined;
    actionError.value = "任务分配失败，文章状态可能已经变化，请刷新后重试。";
  } finally {
    busy.value = false;
  }
}

watch(
  () => [route.params.paperId, route.query.candidate_id],
  load,
  { immediate: true },
);
</script>

<template>
  <div class="detail-page admin-page review-workspace">
    <RouterLink class="back-link" :to="{ name: 'admin-papers', query: route.query.candidate_id ? { candidate_id: route.query.candidate_id } : {} }">← 返回文章目录</RouterLink>
    <section v-if="state === 'loading'" class="page-state"><span class="state-spinner"></span><p>正在读取文章信息…</p></section>
    <section v-else-if="state === 'not-found'" class="page-state"><span>404</span><h1>未找到文章</h1><p>该文章可能不属于当前数据库或导入候选。</p></section>
    <section v-else-if="state === 'error'" class="page-state" role="alert"><span class="state-symbol is-error">!</span><h1>暂时无法读取文章</h1><small v-if="requestId">请求编号 · {{ requestId }}</small><button class="button-secondary" type="button" @click="load">重新加载</button></section>

    <template v-else-if="detail">
      <header class="paper-header page-heading">
        <div>
          <div class="identifiers"><code class="status-chip">{{ detail.paper.paper_key }}</code><code v-if="detail.paper.doi" class="status-chip">{{ detail.paper.doi }}</code></div>
          <h1>{{ detail.paper.title }}</h1>
          <p>{{ detail.paper.year || "年份未知" }}<template v-if="detail.paper.target"> · {{ detail.paper.target }}</template></p>
        </div>
        <aside class="panel">
          <span>{{ detail.source.title }}</span>
          <strong class="status-chip" :data-verification="detail.paper.verification_status">{{ detail.paper.verification_status === "human_verified" ? "已人工核验" : "未验证" }}</strong>
          <small class="status-chip" :data-status="detail.paper.publication_status">{{ detail.paper.publication_status === "published" ? "已发布" : "未发布" }}</small>
        </aside>
      </header>

      <section class="workspace-grid">
        <div class="main-column">
          <section class="panel quality-panel">
            <div class="section-heading"><div><p class="eyebrow">DATABASE SUMMARY</p><h2>数据库内容</h2></div></div>
            <div class="quality-grid">
              <div data-quality-compounds><strong>{{ detail.paper.quality.compounds }}</strong><span>个分子</span></div>
              <div><strong>{{ detail.paper.quality.confirmed_structures }} / {{ detail.paper.quality.structures }}</strong><span>结构已确认</span></div>
              <div><strong>{{ detail.paper.quality.evidence }}</strong><span>条证据</span></div>
              <div><strong>{{ detail.paper.quality.activities }}</strong><span>条活性记录</span></div>
              <div><strong>{{ detail.paper.quality.lineage_edges }}</strong><span>条优化关系</span></div>
              <div><strong>{{ detail.paper.quality.visual_objects }}</strong><span>个图像对象</span></div>
            </div>
          </section>

          <section class="panel source-panel">
            <div><p class="eyebrow">SOURCE EVIDENCE</p><h2>原始文献</h2><p>在新页面打开数据库登记的原始 PDF，用于逐项人工核查。</p></div>
            <a class="button-secondary" data-source-pdf :href="detail.source_pdf_url" target="_blank" rel="noopener">查看原始 PDF ↗</a>
          </section>
        </div>

        <aside class="review-panel panel">
          <p class="eyebrow">TRACEABLE REVIEW</p><h2>人工核验与修改</h2>
          <div class="current-state"><span>当前状态</span><strong class="status-chip" :data-state="detail.paper.workflow_state">{{ adminPaperWorkflowLabel(detail.paper.workflow_state) }}</strong></div>
          <template v-if="reviewEntry">
            <p v-if="detail.paper.task">已分配给 {{ detail.paper.task.assignee_display_name }}。所有修改将记录在 changeset 中，可审批、追溯和回滚。</p>
            <RouterLink class="button-primary full" data-open-review :to="reviewEntry">进入修改工作区</RouterLink>
          </template>
          <form v-else-if="detail.paper.publication_status === 'published'" data-assignment-form @submit.prevent="assignPaper">
            <p>{{ blockerText }}</p>
            <label class="form-field">核查员<select id="paper-reviewer" v-model="reviewerId" class="form-control" required><option value="" disabled>请选择</option><option v-for="reviewer in enabledReviewers" :key="reviewer.id" :value="reviewer.id">{{ reviewer.display_name }} · {{ reviewer.username }}</option></select></label>
            <label class="form-field">优先级<input v-model.number="priority" class="form-control" type="number" min="0" max="100"></label>
            <button class="button-primary full" data-assign-paper type="submit" :disabled="busy || !reviewerId">{{ busy ? "正在分配…" : "分配并准备修改" }}</button>
          </form>
          <template v-else>
            <p>{{ blockerText }}</p>
            <RouterLink class="button-secondary full" to="/admin/imports">前往导入审批</RouterLink>
          </template>
          <p v-if="actionError" class="action-error inline-feedback is-error" role="alert">{{ actionError }}<small v-if="requestId">请求编号 · {{ requestId }}</small></p>
        </aside>
      </section>
    </template>
  </div>
</template>

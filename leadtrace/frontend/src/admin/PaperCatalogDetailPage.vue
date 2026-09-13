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
  <div class="detail-page">
    <RouterLink class="back-link" :to="{ name: 'admin-papers', query: route.query.candidate_id ? { candidate_id: route.query.candidate_id } : {} }">← 返回文章目录</RouterLink>
    <section v-if="state === 'loading'" class="page-state"><span class="spinner"></span><p>正在读取文章信息…</p></section>
    <section v-else-if="state === 'not-found'" class="page-state"><span>404</span><h1>未找到文章</h1><p>该文章可能不属于当前数据库或导入候选。</p></section>
    <section v-else-if="state === 'error'" class="page-state" role="alert"><span>!</span><h1>暂时无法读取文章</h1><small v-if="requestId">请求编号 · {{ requestId }}</small><button type="button" @click="load">重新加载</button></section>

    <template v-else-if="detail">
      <header class="paper-header">
        <div>
          <div class="identifiers"><code>{{ detail.paper.paper_key }}</code><code v-if="detail.paper.doi">{{ detail.paper.doi }}</code></div>
          <h1>{{ detail.paper.title }}</h1>
          <p>{{ detail.paper.year || "年份未知" }}<template v-if="detail.paper.target"> · {{ detail.paper.target }}</template></p>
        </div>
        <aside>
          <span>{{ detail.source.title }}</span>
          <strong>{{ detail.paper.verification_status === "human_verified" ? "已人工核验" : "未验证" }}</strong>
          <small>{{ detail.paper.publication_status === "published" ? "已发布" : "未发布" }}</small>
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
          <div class="current-state"><span>当前状态</span><strong>{{ detail.paper.workflow_state }}</strong></div>
          <template v-if="reviewEntry">
            <p v-if="detail.paper.task">已分配给 {{ detail.paper.task.assignee_display_name }}。所有修改将记录在 changeset 中，可审批、追溯和回滚。</p>
            <RouterLink class="button-primary full" data-open-review :to="reviewEntry">进入修改工作区</RouterLink>
          </template>
          <form v-else-if="detail.paper.publication_status === 'published'" data-assignment-form @submit.prevent="assignPaper">
            <p>{{ blockerText }}</p>
            <label>核查员<select id="paper-reviewer" v-model="reviewerId" required><option value="" disabled>请选择</option><option v-for="reviewer in enabledReviewers" :key="reviewer.id" :value="reviewer.id">{{ reviewer.display_name }} · {{ reviewer.username }}</option></select></label>
            <label>优先级<input v-model.number="priority" type="number" min="0" max="100"></label>
            <button class="button-primary full" data-assign-paper type="submit" :disabled="busy || !reviewerId">{{ busy ? "正在分配…" : "分配并准备修改" }}</button>
          </form>
          <template v-else>
            <p>{{ blockerText }}</p>
            <RouterLink class="button-secondary full" to="/admin/imports">前往导入审批</RouterLink>
          </template>
          <p v-if="actionError" class="action-error" role="alert">{{ actionError }}<small v-if="requestId">请求编号 · {{ requestId }}</small></p>
        </aside>
      </section>
    </template>
  </div>
</template>

<style scoped>
.detail-page{max-width:1460px;margin:auto;padding:clamp(26px,4vw,52px)}.back-link{display:inline-block;margin-bottom:24px;color:var(--forest-750);font-size:.73rem;font-weight:700;text-decoration:none}.paper-header{display:flex;justify-content:space-between;gap:30px;padding-bottom:28px;border-bottom:1px solid var(--line)}.paper-header h1{max-width:900px;margin:12px 0;color:var(--ink-950);font:600 clamp(1.8rem,3vw,2.8rem)/1.2 Georgia,"Noto Serif SC Variable",serif}.paper-header p{margin:0;color:var(--ink-650)}.identifiers{display:flex;gap:8px;flex-wrap:wrap}.identifiers code{padding:4px 7px;border-radius:5px;color:var(--forest-750);background:var(--forest-100);font-size:.67rem}.paper-header>aside{display:grid;min-width:200px;align-content:start;gap:8px;padding:15px;border-left:3px solid var(--forest-750);background:#fff}.paper-header>aside span{font-size:.72rem;font-weight:750}.paper-header>aside strong,.paper-header>aside small{width:max-content;padding:4px 7px;border-radius:99px;font-size:.65rem}.paper-header>aside strong{color:#8b3d2f;background:#fbe9e3}.paper-header>aside small{background:#eef2ef;color:var(--ink-650)}
.workspace-grid{display:grid;grid-template-columns:minmax(0,1.8fr) minmax(310px,.75fr);gap:24px;margin-top:30px}.main-column{display:grid;gap:24px}.panel{padding:22px;border:1px solid var(--line);background:#fff;box-shadow:var(--shadow-sm)}.section-heading h2,.panel h2{margin:0;color:var(--ink-950);font:600 1.3rem/1.25 Georgia,"Noto Serif SC Variable",serif}.quality-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;margin-top:18px;background:var(--line)}.quality-grid div{display:grid;gap:5px;padding:18px;background:#fbfcfb}.quality-grid strong{color:var(--forest-900);font:600 1.6rem/1 Georgia,serif}.quality-grid span{color:var(--ink-500);font-size:.67rem}.source-panel{display:flex;align-items:center;justify-content:space-between;gap:20px}.source-panel h2{margin:0}.source-panel p:last-child{margin:8px 0 0;color:var(--ink-650);font-size:.76rem}.button-secondary{display:inline-flex;min-height:42px;align-items:center;justify-content:center;padding:9px 14px;border:1px solid var(--line-strong);border-radius:7px;color:var(--ink-650);background:#fff;font-size:.72rem;font-weight:700;text-decoration:none;cursor:pointer;white-space:nowrap}
.review-panel{align-self:start;position:sticky;top:96px}.review-panel>h2{margin-bottom:16px}.review-panel p{color:var(--ink-650);font-size:.74rem;line-height:1.7}.current-state{display:grid;gap:4px;margin-bottom:14px;padding:12px;background:#f5f8f6}.current-state span{color:var(--ink-500);font-size:.64rem}.current-state strong{color:var(--forest-750);font-size:.7rem}.review-panel form,.review-panel label{display:grid;gap:7px}.review-panel form{gap:12px}.review-panel label{color:var(--ink-650);font-size:.68rem;font-weight:700}.review-panel select,.review-panel input{min-height:40px;padding:8px 10px;border:1px solid var(--line-strong);border-radius:6px;background:#fff}.full{width:100%;margin-top:8px;text-decoration:none}.action-error{padding:10px;color:var(--danger)!important;background:var(--danger-soft)}.action-error small{display:block;margin-top:4px}.page-state{display:flex;min-height:360px;flex-direction:column;align-items:center;justify-content:center;gap:8px;color:var(--ink-650);text-align:center}.page-state h1,.page-state p{margin:0}.page-state>span{display:grid;width:48px;height:48px;place-items:center;border:1px solid var(--line);border-radius:50%}.spinner{border-top-color:var(--forest-750)!important;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:900px){.paper-header,.source-panel{align-items:flex-start;flex-direction:column}.paper-header>aside{width:100%}.workspace-grid{grid-template-columns:1fr}.review-panel{position:static}.quality-grid{grid-template-columns:repeat(2,1fr)}}@media(max-width:520px){.quality-grid{grid-template-columns:1fr}}@media(prefers-reduced-motion:reduce){.spinner{animation:none}}
</style>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { ApiError } from "../../api/client";
import { fetchPaperDetail } from "../../api/published";
import type { Changeset, PaperDetailResponse, ReviewTask } from "../../api/schema";
import {
  createChangeset,
  fetchChangesets,
  fetchReviewTasks,
} from "../api";

type ViewState = "loading" | "ready" | "error";

const route = useRoute();
const router = useRouter();
const state = ref<ViewState>("loading");
const tasks = ref<ReviewTask[]>([]);
const changesets = ref<Changeset[]>([]);
const selectedTask = ref<ReviewTask | null>(null);
const paperDetail = ref<PaperDetailResponse | null>(null);
const title = ref("");
const reason = ref("");
const busy = ref(false);
const formError = ref<string>();
const requestId = ref<string>();
let loadGeneration = 0;

const taskId = computed(() => (
  typeof route.query.task === "string" ? route.query.task : ""
));

const statusLabels: Record<Changeset["workflow_state"], string> = {
  draft: "草稿",
  revised_draft: "修订草稿",
  submitted: "待审批",
  changes_requested: "要求修改",
  approved: "已批准",
  published: "已发布",
  superseded: "已被替代",
  rejected: "已拒绝",
};

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Shanghai",
  }).format(new Date(value));
}

async function load(): Promise<void> {
  const generation = ++loadGeneration;
  const requestedTaskId = taskId.value;
  state.value = "loading";
  requestId.value = undefined;
  formError.value = undefined;
  selectedTask.value = null;
  paperDetail.value = null;
  try {
    const [taskPayload, changesetPayload] = await Promise.all([
      fetchReviewTasks(),
      fetchChangesets(),
    ]);
    if (generation !== loadGeneration || requestedTaskId !== taskId.value) return;
    tasks.value = taskPayload;
    changesets.value = changesetPayload;
    if (requestedTaskId) {
      const existing = changesetPayload.find((entry) => entry.review_task_id === requestedTaskId);
      if (existing) {
        await router.replace(`/review/changesets/${existing.id}`);
        return;
      }
      const task = taskPayload.find((entry) => entry.id === requestedTaskId) ?? null;
      if (!task) throw new Error("Task is not available");
      const detail = await fetchPaperDetail(task.paper_id);
      if (generation !== loadGeneration || requestedTaskId !== taskId.value) return;
      selectedTask.value = task;
      paperDetail.value = detail;
      title.value = `核查 ${detail.paper.paper_key} 的文献元数据与证据`;
      reason.value = "逐项对照原始文献进行人工核查";
    }
    state.value = "ready";
  } catch (error) {
    if (generation !== loadGeneration || requestedTaskId !== taskId.value) return;
    state.value = "error";
    requestId.value = error instanceof ApiError ? error.requestId : undefined;
  }
}

async function createDraft(): Promise<void> {
  if (!selectedTask.value || !paperDetail.value || busy.value) return;
  const generation = loadGeneration;
  const selectedTaskId = selectedTask.value.id;
  const selectedPaperId = selectedTask.value.paper_id;
  const selectedReleaseId = paperDetail.value.release.id;
  const cleanTitle = title.value.trim();
  const cleanReason = reason.value.trim();
  if (!cleanTitle || !cleanReason) {
    formError.value = "标题和修改原因均不能为空。";
    return;
  }
  busy.value = true;
  formError.value = undefined;
  requestId.value = undefined;
  try {
    const changeset = await createChangeset({
      review_task_id: selectedTaskId,
      paper_id: selectedPaperId,
      base_release_id: selectedReleaseId,
      title: cleanTitle,
      reason: cleanReason,
      initialize_from_base: true,
    });
    if (generation !== loadGeneration || taskId.value !== selectedTaskId) return;
    await router.replace(`/review/changesets/${changeset.id}`);
  } catch (error) {
    if (generation !== loadGeneration || taskId.value !== selectedTaskId) return;
    requestId.value = error instanceof ApiError ? error.requestId : undefined;
    formError.value = error instanceof ApiError && error.status === 409
      ? "该任务已创建修改集，请重新载入任务列表。"
      : "草稿未能完整创建，请稍后重试。";
  } finally {
    if (generation === loadGeneration && taskId.value === selectedTaskId) {
      busy.value = false;
    }
  }
}

watch(() => route.fullPath, load, { immediate: true });
</script>

<template>
  <div class="review-page changeset-index-page review-workspace">
    <section v-if="state === 'loading'" class="index-state page-state" aria-live="polite">
      <span class="state-spinner" aria-hidden="true"></span>
      <p>正在准备核查工作区…</p>
    </section>

    <section v-else-if="state === 'error'" class="index-state page-state" role="alert">
      <span class="state-symbol" aria-hidden="true">!</span>
      <h1>暂时无法准备核查工作区</h1>
      <p>请从任务列表重新进入，或将请求编号提供给管理员。</p>
      <small v-if="requestId">请求编号 · {{ requestId }}</small>
      <button class="button-secondary" type="button" @click="load">重新加载</button>
    </section>

    <template v-else-if="selectedTask && paperDetail">
      <header class="index-heading page-heading">
        <div>
          <RouterLink class="back-link" to="/review/tasks">← 返回核查任务</RouterLink>
          <p class="eyebrow">NEW CHANGESET</p>
          <h1>创建核查草稿</h1>
          <p>从固定发布版本复制完整快照，草稿不会影响 Visitor 当前看到的数据。</p>
        </div>
      </header>

      <div class="creation-layout">
        <form class="creation-form panel" data-create-changeset @submit.prevent="createDraft">
          <div class="form-heading">
            <div>
              <span>Paper</span>
              <h2>{{ paperDetail.paper.title }}</h2>
            </div>
            <code>{{ paperDetail.paper.paper_key }}</code>
          </div>
          <dl class="paper-facts">
            <div><dt>DOI</dt><dd>{{ paperDetail.paper.doi || "—" }}</dd></div>
            <div><dt>研究靶点</dt><dd>{{ paperDetail.paper.target || "—" }}</dd></div>
            <div><dt>发布版本</dt><dd>{{ paperDetail.release.key }}</dd></div>
            <div><dt>证据记录</dt><dd>{{ paperDetail.evidence.length }}</dd></div>
          </dl>
          <label for="new-changeset-title">修改集标题</label>
          <input id="new-changeset-title" v-model="title" class="form-control" type="text" maxlength="255" required>
          <label for="new-changeset-reason">修改原因</label>
          <textarea id="new-changeset-reason" v-model="reason" class="form-control" rows="5" maxlength="4000" required></textarea>
          <div v-if="formError" class="form-alert" role="alert">
            <p>{{ formError }}</p>
            <small v-if="requestId">请求编号 · {{ requestId }}</small>
          </div>
          <button class="button-primary" type="submit" :disabled="busy">
            {{ busy ? "正在复制发布快照…" : "创建草稿并进入工作区" }}
          </button>
        </form>

        <aside class="creation-notes panel">
          <p class="eyebrow">DRAFT BOUNDARY</p>
          <h2>草稿边界</h2>
          <ol>
            <li><span>01</span><p><strong>固定基线</strong>使用 {{ paperDetail.release.title }} 作为本次核查基线。</p></li>
            <li><span>02</span><p><strong>隔离修改</strong>Paper 与证据 Revision 会复制到独立修改集。</p></li>
            <li><span>03</span><p><strong>审批发布</strong>提交后先进入待审批，管理员批准后才可发布。</p></li>
          </ol>
        </aside>
      </div>
    </template>

    <template v-else>
      <header class="index-heading page-heading">
        <div>
          <p class="eyebrow">CHANGESETS</p>
          <h1>修改集</h1>
          <p>集中查看草稿、待审批和已完成的核查记录。</p>
        </div>
        <RouterLink class="button-primary" to="/review/tasks">从任务开始核查</RouterLink>
      </header>
      <section v-if="changesets.length" class="changeset-table-wrap panel table-wrap">
        <table class="data-table">
          <thead><tr><th>修改集</th><th>状态</th><th>版本</th><th>最近更新</th><th><span class="sr-only">操作</span></th></tr></thead>
          <tbody>
            <tr v-for="entry in changesets" :key="entry.id" data-changeset-row>
              <th><strong>{{ entry.title }}</strong><code>{{ entry.id }}</code></th>
              <td><span class="status-label status-chip" :data-status="entry.workflow_state">{{ statusLabels[entry.workflow_state] }}</span></td>
              <td>{{ entry.version }}</td>
              <td>{{ formatDate(entry.updated_at) }}</td>
              <td><RouterLink :to="`/review/changesets/${entry.id}`">打开</RouterLink></td>
            </tr>
          </tbody>
        </table>
      </section>
      <section v-else class="empty-index page-state">
        <span aria-hidden="true">—</span>
        <h2>暂无修改集</h2>
        <p>从已分配的核查任务创建第一个草稿。</p>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";

import { ApiError } from "../../api/client";
import type { Changeset, ReviewTask } from "../../api/schema";
import { fetchChangesets, fetchReviewTasks } from "../api";

type ViewState = "loading" | "ready" | "error";

const state = ref<ViewState>("loading");
const tasks = ref<ReviewTask[]>([]);
const changesets = ref<Changeset[]>([]);
const requestId = ref<string>();

const changesetByTask = computed(() => new Map(
  changesets.value.map((changeset) => [changeset.review_task_id, changeset]),
));

const orderedTasks = computed(() => [...tasks.value].sort((left, right) => {
  if (left.status === "in_progress" && right.status !== "in_progress") return -1;
  if (right.status === "in_progress" && left.status !== "in_progress") return 1;
  if (left.priority !== right.priority) return right.priority - left.priority;
  return Date.parse(right.updated_at) - Date.parse(left.updated_at);
}));

const statusLabels: Record<ReviewTask["status"], string> = {
  open: "待开始",
  in_progress: "核查中",
  submitted: "待审批",
  changes_requested: "需修改",
  completed: "已完成",
};

function statusLabel(status: ReviewTask["status"]): string {
  return statusLabels[status];
}

function priorityLabel(priority: number): string {
  if (priority >= 70) return "高优先级";
  if (priority >= 35) return "中优先级";
  return "普通优先级";
}

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
  state.value = "loading";
  requestId.value = undefined;
  try {
    const [taskPayload, changesetPayload] = await Promise.all([
      fetchReviewTasks(),
      fetchChangesets(),
    ]);
    tasks.value = taskPayload;
    changesets.value = changesetPayload;
    state.value = "ready";
  } catch (error) {
    state.value = "error";
    requestId.value = error instanceof ApiError ? error.requestId : undefined;
  }
}

onMounted(load);
</script>

<template>
  <div class="review-page task-list-page">
    <header class="review-heading">
      <div>
        <p class="eyebrow">REVIEW QUEUE</p>
        <h1>核查任务</h1>
        <p class="heading-description">按优先级和当前状态整理分配给你的文献核查工作。</p>
      </div>
      <div class="queue-summary" aria-label="任务摘要">
        <span>{{ orderedTasks.length }}</span>
        <small>项任务</small>
      </div>
    </header>

    <section v-if="state === 'loading'" class="review-state" aria-live="polite">
      <span class="state-spinner" aria-hidden="true"></span>
      <p>正在读取核查任务…</p>
    </section>

    <section v-else-if="state === 'error'" class="review-state is-error" role="alert">
      <span class="state-symbol" aria-hidden="true">!</span>
      <h2>暂时无法读取任务</h2>
      <p>请稍后重试，或将请求编号提供给管理员。</p>
      <small v-if="requestId">请求编号 · {{ requestId }}</small>
      <button class="button-secondary" type="button" @click="load">重新加载</button>
    </section>

    <section v-else-if="orderedTasks.length === 0" class="review-state" data-empty-state>
      <span class="state-symbol" aria-hidden="true">—</span>
      <h2>暂无待核查任务</h2>
      <p>管理员分配新的文献后，任务会出现在这里。</p>
    </section>

    <section v-else class="task-table-section" aria-labelledby="task-table-title">
      <div class="table-heading">
        <div>
          <p class="eyebrow">ASSIGNED WORK</p>
          <h2 id="task-table-title">我的任务</h2>
        </div>
        <span class="table-note">更新于最近一次状态变更</span>
      </div>
      <div class="table-wrap">
        <table class="task-table">
          <thead>
            <tr>
              <th scope="col">文献</th>
              <th scope="col">状态</th>
              <th scope="col">优先级</th>
              <th scope="col">最近更新</th>
              <th scope="col"><span class="sr-only">操作</span></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="task in orderedTasks"
              :key="task.id"
              class="task-row"
              data-review-task
              :data-task-id="task.id"
            >
              <th scope="row">
                <span class="paper-label">Paper</span>
                <code>{{ task.paper_id }}</code>
              </th>
              <td>
                <span class="status-badge" :data-status="task.status">
                  <span class="status-dot" aria-hidden="true"></span>
                  {{ statusLabel(task.status) }}
                </span>
              </td>
              <td>
                <span class="priority-label" :data-priority="priorityLabel(task.priority)">
                  {{ priorityLabel(task.priority) }}
                </span>
              </td>
              <td class="updated-at">{{ formatDate(task.updated_at) }}</td>
              <td class="task-action">
                <RouterLink
                  v-if="changesetByTask.get(task.id)"
                  class="button-primary compact-action"
                  :to="`/review/changesets/${changesetByTask.get(task.id)?.id}`"
                >继续核查</RouterLink>
                <RouterLink
                  v-else
                  class="button-secondary compact-action"
                  :to="{ path: '/review/changesets', query: { task: task.id } }"
                >开始核查</RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.review-page { max-width: 1380px; margin: 0 auto; padding: clamp(28px, 5vw, 58px); }
.review-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; padding-bottom: 30px; border-bottom: 1px solid var(--line); }
.review-heading h1 { margin: 0; color: var(--ink-950); font: 600 clamp(2rem, 3vw, 3rem)/1.15 Georgia, "Noto Serif SC Variable", serif; }
.heading-description { max-width: 600px; margin: 13px 0 0; color: var(--ink-650); font-size: .9rem; line-height: 1.7; }
.queue-summary { display: flex; min-width: 112px; flex-direction: column; align-items: flex-end; padding: 12px 0 2px; color: var(--forest-900); }
.queue-summary span { font: 600 2.7rem/1 Georgia, "Noto Serif SC Variable", serif; }
.queue-summary small { margin-top: 6px; color: var(--ink-500); font-size: .7rem; }
.task-table-section { margin-top: 40px; }
.table-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 18px; margin-bottom: 15px; }
.table-heading h2 { margin: 0; color: var(--ink-950); font: 600 1.35rem/1.2 Georgia, "Noto Serif SC Variable", serif; }
.table-note { color: var(--ink-500); font-size: .7rem; }
.table-wrap { overflow-x: auto; border-top: 2px solid var(--forest-900); background: var(--paper); box-shadow: var(--shadow-sm); }
.task-table { width: 100%; border-collapse: collapse; min-width: 720px; }
.task-table th, .task-table td { padding: 17px 18px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: middle; }
.task-table thead th { color: var(--ink-500); background: #f8faf8; font-size: .68rem; font-weight: 760; letter-spacing: .08em; }
.task-table tbody th { color: var(--ink-800); font-size: .78rem; font-weight: 600; }
.task-row:hover { background: #fbfdfb; }
.paper-label, .task-table code { display: block; }
.paper-label { margin-bottom: 5px; color: var(--gold-700); font-size: .63rem; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; }
.task-table code { color: var(--ink-650); font-size: .72rem; user-select: all; }
.status-badge { display: inline-flex; align-items: center; gap: 7px; color: var(--ink-650); font-size: .75rem; font-weight: 680; white-space: nowrap; }
.status-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--ink-500); }
.status-badge[data-status="in_progress"] .status-dot { background: #c2872d; }
.status-badge[data-status="submitted"] .status-dot { background: #3e7795; }
.status-badge[data-status="changes_requested"] .status-dot { background: var(--danger); }
.status-badge[data-status="completed"] .status-dot { background: #438263; }
.priority-label { color: var(--ink-650); font-size: .74rem; }
.priority-label[data-priority="高优先级"] { color: var(--danger); font-weight: 760; }
.updated-at { color: var(--ink-500); font-size: .73rem; white-space: nowrap; }
.task-action { width: 145px; text-align: right !important; }
.compact-action { min-height: 36px; padding: 7px 12px; font-size: .72rem; text-decoration: none; white-space: nowrap; }
.review-state { display: flex; min-height: 300px; flex-direction: column; align-items: center; justify-content: center; gap: 8px; color: var(--ink-650); text-align: center; }
.review-state h2 { margin: 7px 0 0; color: var(--ink-950); font: 600 1.45rem/1.2 Georgia, "Noto Serif SC Variable", serif; }
.review-state p { margin: 0; font-size: .82rem; }
.review-state small { color: var(--ink-500); font-size: .68rem; }
.state-symbol { display: grid; width: 50px; height: 50px; place-items: center; border: 1px solid var(--line-strong); border-radius: 50%; color: var(--forest-750); font: 600 1.35rem/1 Georgia, serif; }
.state-spinner { width: 24px; height: 24px; border: 2px solid var(--line); border-top-color: var(--forest-750); border-radius: 50%; animation: spin .8s linear infinite; }
.review-state .button-secondary { margin-top: 10px; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 700px) { .review-heading { align-items: flex-start; flex-direction: column; } .queue-summary { align-items: flex-start; } .table-heading { align-items: flex-start; flex-direction: column; gap: 7px; } .table-wrap { margin-inline: -10px; } }
@media (prefers-reduced-motion: reduce) { .state-spinner { animation: none; } }
</style>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";

import { ApiError } from "../../api/client";
import type { Changeset, ReviewTask } from "../../api/schema";
import { fetchChangesets, fetchReviewTasks } from "../api";
import MoleculeObjectQueue from "./MoleculeObjectQueue.vue";

type ViewState = "loading" | "ready" | "error";

const state = ref<ViewState>("loading");
const route = useRoute();
const router = useRouter();
const tasks = ref<ReviewTask[]>([]);
const changesets = ref<Changeset[]>([]);
const requestId = ref<string>();
const activeTab = computed(() => (
  route.query.tab === "molecules" ? "molecules" : "papers"
));

function selectTab(tab: "papers" | "molecules"): void {
  const query = { ...route.query };
  if (tab === "molecules") query.tab = "molecules";
  else {
    delete query.tab;
    delete query.status;
    delete query.object_type;
    delete query.has_blocker;
  }
  void router.replace({ path: route.path, query });
}

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
  <div class="review-page task-list-page review-workspace">
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

    <nav class="workspace-tabs task-queue-tabs" role="tablist" aria-label="核查任务类型">
      <button
        type="button"
        role="tab"
        :aria-selected="activeTab === 'papers'"
        :aria-current="activeTab === 'papers' ? 'page' : undefined"
        @click="selectTab('papers')"
      >Paper 任务 · {{ orderedTasks.length }}</button>
      <button
        type="button"
        role="tab"
        :aria-selected="activeTab === 'molecules'"
        :aria-current="activeTab === 'molecules' ? 'page' : undefined"
        @click="selectTab('molecules')"
      >分子对象</button>
    </nav>

    <MoleculeObjectQueue v-if="activeTab === 'molecules'" />

    <section v-else-if="state === 'loading'" class="review-state page-state" aria-live="polite">
      <span class="state-spinner" aria-hidden="true"></span>
      <p>正在读取核查任务…</p>
    </section>

    <section v-else-if="state === 'error'" class="review-state page-state is-error" role="alert">
      <span class="state-symbol" aria-hidden="true">!</span>
      <h2>暂时无法读取任务</h2>
      <p>请稍后重试，或将请求编号提供给管理员。</p>
      <small v-if="requestId">请求编号 · {{ requestId }}</small>
      <button class="button-secondary" type="button" @click="load">重新加载</button>
    </section>

    <section v-else-if="orderedTasks.length === 0" class="review-state page-state" data-empty-state>
      <span class="state-symbol" aria-hidden="true">—</span>
      <h2>暂无待核查任务</h2>
      <p>管理员分配新的文献后，任务会出现在这里。</p>
    </section>

    <section v-else class="task-table-section panel" aria-labelledby="task-table-title">
      <div class="table-heading">
        <div>
          <p class="eyebrow">ASSIGNED WORK</p>
          <h2 id="task-table-title">我的任务</h2>
        </div>
        <span class="table-note">更新于最近一次状态变更</span>
      </div>
      <div class="table-wrap">
        <table class="task-table data-table">
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
                <span class="status-badge status-chip" :data-status="task.status">
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

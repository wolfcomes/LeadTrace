<script setup lang="ts">
import { t } from "../../i18n";
import { computed, onMounted, ref } from "vue";

import { ApiError } from "../../api/client";
import { listReviewTasks } from "../../v2/api";
import type { ReviewTask, ReviewTaskList } from "../../v2/types";

type ViewState = "loading" | "ready" | "error";
const state = ref<ViewState>("loading");
const payload = ref<ReviewTaskList>();
const requestId = ref<string>();

const tasks = computed(() => [...(payload.value?.items ?? [])].sort((left, right) => {
  const rank = { changes_requested: 0, assigned: 1, submitted: 2, approved: 3 } as const;
  return rank[left.task_status] - rank[right.task_status]
    || left.paper_key.localeCompare(right.paper_key);
}));

function taskStatusLabel(task: ReviewTask): string {
  return { assigned: "待填写", submitted: "待 Admin 审批", changes_requested: "需修改", approved: "已批准" }[task.task_status];
}

function actionLabel(task: ReviewTask): string {
  if (task.task_status === "changes_requested") return "继续修改";
  if (task.task_status === "submitted") return "查看提交";
  if (task.task_status === "approved") return "查看记录";
  return "开始填写";
}

async function load(): Promise<void> {
  state.value = "loading";
  requestId.value = undefined;
  try {
    payload.value = await listReviewTasks();
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
      <div><p class="eyebrow">REVIEWER · ASSIGNED PAPERS</p><h1>{{ t("我的任务") }}</h1><p>{{ t("每项任务对应一篇 Paper。可直接从空白 Workspace 开始人工填写。") }}</p></div>
      <div class="queue-summary" :aria-label='t("任务摘要")'><span>{{ payload?.total ?? 0 }}</span><small>{{ t("篇文章") }}</small></div>
    </header>
    <section v-if="state === 'loading'" class="page-state" aria-live="polite"><span class="state-spinner" aria-hidden="true"></span><p>{{ t("正在读取我的任务…") }}</p></section>
    <section v-else-if="state === 'error'" class="page-state" role="alert"><span class="state-symbol is-error">!</span><h2>{{ t("暂时无法读取任务") }}</h2><small v-if="requestId">{{ t("请求编号 ·") }}{{ requestId }}</small><button class="button-secondary" type="button" @click="load">{{ t("重新加载") }}</button></section>
    <section v-else-if="tasks.length === 0" class="page-state" data-empty-state><span class="state-symbol" aria-hidden="true">—</span><h2>{{ t("暂无任务") }}</h2><p>{{ t("Admin 分配 Paper 后会显示在这里。") }}</p></section>
    <section v-else class="task-table-section panel">
      <div class="table-heading"><div><p class="eyebrow">ASSIGNED WORK</p><h2>{{ t("Paper 任务") }}</h2></div></div>
      <div class="table-wrap"><table class="task-table data-table">
        <thead><tr><th>{{ t("文章") }}</th><th>{{ t("状态") }}</th><th>Workspace</th><th><span class="sr-only">{{ t("操作") }}</span></th></tr></thead>
        <tbody><tr v-for="task in tasks" :key="task.review_task_id" data-review-task>
          <th scope="row"><code>{{ task.paper_key }}</code><strong>{{ task.title }}</strong></th>
          <td><span class="status-chip" :data-status="task.task_status">{{ t(taskStatusLabel(task)) }}</span></td>
          <td><span>v{{ task.workspace_version }}</span><small>{{ task.workspace_state }}</small></td>
          <td class="table-actions"><RouterLink class="button-primary compact-action" data-open-workspace :to="{ path: `/review/papers/${task.paper_id}`, query: { workspace: task.workspace_id } }">{{ t(actionLabel(task)) }}</RouterLink></td>
        </tr></tbody>
      </table></div>
    </section>
  </div>
</template>

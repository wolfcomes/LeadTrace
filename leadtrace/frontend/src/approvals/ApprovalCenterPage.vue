<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ApiError } from "../api/client";
import { listAdminSubmissions } from "../v2/api";
import type { AdminSubmissionList } from "../v2/types";

const submissions = ref<AdminSubmissionList["items"]>([]);
const loading = ref(true);
const error = ref<string | null>(null);

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Shanghai" }).format(new Date(value));
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    submissions.value = (await listAdminSubmissions()).items;
  } catch (caught) {
    error.value = caught instanceof ApiError ? `待审批提交未能读取。请求编号：${caught.requestId ?? "未知"}` : "待审批提交未能读取。";
  } finally {
    loading.value = false;
  }
}
onMounted(load);
</script>

<template>
  <div class="admin-page submission-queue-page">
    <header class="page-heading">
      <div><p class="eyebrow">FROZEN SUBMISSIONS</p><h1>提交审批</h1><p>核对 Reviewer 冻结快照、结构来源、Lineage、Evidence 与完整修改历史。</p></div>
      <span class="status-chip is-pending">{{ submissions.length }} 项待审批</span>
    </header>
    <p v-if="error" class="message inline-feedback is-error" role="alert">{{ error }}</p>
    <section class="admin-panel panel table-wrap" aria-label="待审批提交">
      <div class="section-heading">
        <div><p class="eyebrow">QUEUE</p><h2>Reviewer Submissions</h2></div>
        <button class="button-secondary" type="button" :disabled="loading" @click="load">刷新</button>
      </div>
      <table v-if="submissions.length" class="data-table">
        <thead><tr><th>文章</th><th>提交</th><th>Content hash</th><th>提交时间</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="item in submissions" :key="item.submission_id" data-submission-row>
            <td><strong>{{ item.title }}</strong><br><code>{{ item.paper_key }}</code></td>
            <td>第 {{ item.submission_number }} 次提交</td>
            <td><code>{{ item.content_hash }}</code></td>
            <td>{{ formatDate(item.submitted_at) }}</td>
            <td><RouterLink class="button-secondary" data-open-submission :to="{ name: 'admin-submission-detail', params: { submissionId: item.submission_id } }">核对 →</RouterLink></td>
          </tr>
        </tbody>
      </table>
      <div v-else-if="loading" class="page-state compact" aria-live="polite">正在读取待审批提交…</div>
      <div v-else-if="!error" class="page-state compact"><span class="state-symbol" aria-hidden="true">0</span><h2>当前没有待审批提交</h2><p>Reviewer 提交后会出现在这里。</p></div>
    </section>
  </div>
</template>

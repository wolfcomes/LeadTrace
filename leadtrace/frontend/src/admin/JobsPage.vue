<script setup lang="ts">
import { statusLabel } from "../i18n/status";
import { t, locale } from "../i18n";
import { onMounted, ref } from "vue";
import { fetchAdminJobs, retryAdminJob } from "./api";
const jobs=ref<Record<string,unknown>[]>([]);const loading=ref(true);const error=ref<string|null>(null);const retrying=ref<string|null>(null);
async function load(){try{jobs.value=await fetchAdminJobs()}catch{error.value="任务未能读取。"}finally{loading.value=false}}
async function retry(job:Record<string,unknown>){retrying.value=String(job.id);try{const result=await retryAdminJob(String(job.id));Object.assign(job,result)}catch{error.value="失败任务未能重试。"}finally{retrying.value=null}}
onMounted(load);
</script>
<template>
  <div class="admin-page review-workspace">
    <header class="page-heading"><div><p class="eyebrow">BACKGROUND WORK</p><h1>{{ t("任务队列") }}</h1><p>{{ t("查看裁剪任务状态、失败摘要与可重试操作。") }}</p></div></header>
    <section v-if="loading" class="page-state"><span class="state-spinner"></span></section>
    <section v-else-if="error" class="page-state"><p>{{ t(error) }}</p></section>
    <section v-else class="admin-panel table-wrap">
      <table class="data-table">
        <thead><tr><th>{{ t("任务") }}</th><th>{{ t("状态") }}</th><th>{{ t("错误摘要") }}</th><th>{{ t("创建时间") }}</th><th><span class="sr-only">{{ t("操作") }}</span></th></tr></thead>
        <tbody>
          <tr v-for="job in jobs" :key="String(job.id)" :data-job-id="String(job.id)">
            <td><code>{{ job.id }}</code></td>
            <td><span class="status-chip" :data-status="job.status">{{ statusLabel(job.status) }}</span></td>
            <td>{{ job.error_message || "-" }}</td><td>{{ job.created_at || "-" }}</td>
            <td class="table-actions"><button v-if="job.status==='failed'" class="button-secondary" type="button" :disabled="retrying===String(job.id)" @click="retry(job)">{{ t("重试") }}</button></td>
          </tr>
          <tr v-if="jobs.length===0"><td colspan="5" class="empty">{{ t("暂无任务") }}</td></tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

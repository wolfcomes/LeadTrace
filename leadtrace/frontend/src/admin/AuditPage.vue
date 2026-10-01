<script setup lang="ts">
import { statusLabel } from "../i18n/status";
import { t, locale } from "../i18n";
import { onMounted, ref } from "vue";
import { fetchAdminAudit } from "./api";
const events=ref<Record<string,unknown>[]>([]);const action=ref("");const loading=ref(true);const error=ref<string|null>(null);
async function load(){loading.value=true;try{events.value=await fetchAdminAudit(action.value?{action:action.value}: {})}catch{error.value="审计记录未能读取。"}finally{loading.value=false}}
onMounted(load);
</script>
<template>
  <div class="admin-page review-workspace">
    <header class="page-heading">
      <div><p class="eyebrow">AUDIT TRAIL</p><h1>{{ t("审计记录") }}</h1><p>{{ t("按动作筛选不可变的操作链，并保留请求编号供追查。") }}</p></div>
    </header>
    <section class="admin-panel filter workspace-toolbar">
      <label class="form-label" for="audit-action">{{ t("动作") }}</label>
      <input id="audit-action" v-model="action" class="form-control" :placeholder="t('例如 publish')">
      <button class="button-secondary" type="button" @click="load">{{ t("筛选") }}</button>
    </section>
    <section v-if="loading" class="page-state"><span class="state-spinner"></span></section>
    <section v-else-if="error" class="page-state"><p>{{ t(error) }}</p></section>
    <section v-else class="admin-panel table-wrap">
      <table class="data-table">
        <thead><tr><th>{{ t("序号") }}</th><th>{{ t("动作") }}</th><th>{{ t("目标") }}</th><th>{{ t("结果") }}</th><th>{{ t("请求编号") }}</th><th>{{ t("时间") }}</th></tr></thead>
        <tbody>
          <tr v-for="event in events" :key="String(event.id)">
            <td>{{ event.sequence_number }}</td><td>{{ event.action }}</td><td>{{ event.target_type }} · {{ event.target_id }}</td>
            <td><span class="status-chip" :data-status="event.result">{{ statusLabel(event.result) }}</span></td>
            <td><code>{{ event.request_id }}</code></td><td>{{ event.occurred_at }}</td>
          </tr>
          <tr v-if="events.length===0"><td colspan="6" class="empty">{{ t("暂无审计事件") }}</td></tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

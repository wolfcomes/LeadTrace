<script setup lang="ts">
import { statusLabel } from "../i18n/status";
import { t, locale } from "../i18n";
import { computed, onMounted, ref } from "vue";
import { fetchSystemHealth } from "./api";
const payload=ref<Record<string,unknown>|null>(null);const loading=ref(true);const error=ref<string|null>(null);
const checks = computed(() => (payload.value?.checks ?? {}) as Record<string, Record<string, unknown>>);
onMounted(async()=>{try{payload.value=await fetchSystemHealth()}catch{error.value="系统状态未能读取。"}finally{loading.value=false}});
</script>
<template>
  <div class="admin-page review-workspace">
    <header class="page-heading">
      <div><p class="eyebrow">OPERATIONS</p><h1>{{ t("系统状态") }}</h1><p>{{ t("数据库、资产存储、任务队列和发布状态的可操作摘要。") }}</p></div>
      <span v-if="payload" class="status-chip" :data-status="payload.status">{{ statusLabel(payload.status) }}</span>
    </header>
    <section v-if="loading" class="page-state"><span class="state-spinner"></span></section>
    <section v-else-if="error" class="page-state"><p>{{ t(error) }}</p></section>
    <section v-else class="check-grid">
      <article v-for="(check,name) in checks" :key="name" class="check panel" :data-check="name">
        <div><strong>{{ statusLabel(name) }}</strong><p>{{ check.summary }}</p></div>
        <span :class="['check-status', 'status-chip', `is-${check.status}`]" :data-status="check.status">{{ statusLabel(check.status) }}</span>
      </article>
    </section>
    <p v-if="payload?.request_id" class="request-id">{{ t("请求编号：") }}{{ payload.request_id }}</p>
  </div>
</template>

<script setup lang="ts">
import { statusLabel } from "../i18n/status";
import { t } from "../i18n";
import { ref, watch } from "vue";
import { fetchAdminFiles, fetchFileReferences } from "./api";
import AdminTableState from "./AdminTableState.vue";
import PaperFilters from "./PaperFilters.vue";
import { usePaperFilters } from "./paperFilters";
const PAGE_SIZE = 50;
const articleFilters = usePaperFilters();
const files = ref<Record<string, unknown>[]>([]);
const selected = ref<Record<string, unknown> | null>(null);
const loading = ref(true);
const hasNext = ref(false);
const error = ref<string | null>(null);
let sequence = 0;
let inspection = 0;
async function load() {
  const token = ++sequence;
  inspection++;
  loading.value = true; error.value = null; selected.value = null;
  try {
    const result = await fetchAdminFiles({ ...articleFilters.params.value, limit: PAGE_SIZE + 1, offset: (articleFilters.page.value - 1) * PAGE_SIZE });
    if (token === sequence) { files.value = result.slice(0, PAGE_SIZE); hasNext.value = result.length > PAGE_SIZE; }
  } catch { if (token === sequence) { files.value = []; error.value = "文件列表未能读取。"; } }
  finally { if (token === sequence) loading.value = false; }
}
async function inspect(file: Record<string, unknown>) {
  const token = ++inspection;
  try { const result = await fetchFileReferences(String(file.id)); if (token === inspection) selected.value = result; }
  catch { if (token === inspection) error.value = "文件引用未能读取。"; }
}
watch([articleFilters.params, articleFilters.page], load, { immediate: true });
</script>
<template>
  <div class="admin-page review-workspace">
    <header class="page-heading"><div><p class="eyebrow">ASSET REGISTRY</p><h1>{{ t("文件管理") }}</h1><p>{{ t("按完整性、访问级别和业务反向引用检查托管文件。") }}</p></div></header>
    <PaperFilters :model-value="articleFilters.filters.value" @apply="articleFilters.apply" />
    <AdminTableState :loading="loading" :error="error">
      <section class="admin-panel table-wrap">
        <table class="data-table">
          <thead><tr><th>{{ t("文件") }}</th><th>{{ t("分类") }}</th><th>{{ t("完整性") }}</th><th>{{ t("大小") }}</th><th>{{ t("引用") }}</th></tr></thead>
          <tbody>
            <tr v-for="file in files" :key="String(file.id)">
              <td>{{ file.filename }}</td><td>{{ file.category }}</td>
              <td><span class="status-chip" :data-status="file.integrity">{{ statusLabel(file.integrity) }}</span></td>
              <td>{{ file.byte_size }}</td>
              <td class="table-actions"><button class="button-secondary" type="button" @click="inspect(file)">{{ t("查看反向引用") }}</button></td>
            </tr>
            <tr v-if="files.length===0"><td colspan="5" class="empty">{{ t("暂无托管文件") }}</td></tr>
          </tbody>
        </table>
      </section>
      <nav class="pagination" :aria-label="t('文件分页')">
        <button class="button-secondary" data-previous-page type="button" :disabled="articleFilters.page.value <= 1 || loading" @click="articleFilters.goToPage(articleFilters.page.value - 1)">{{ t('上一页') }}</button>
        <span>{{ t('第 {page} 页', { page: articleFilters.page.value }) }}</span>
        <button class="button-secondary" data-next-page type="button" :disabled="!hasNext || loading" @click="articleFilters.goToPage(articleFilters.page.value + 1)">{{ t('下一页') }}</button>
      </nav>
      <section v-if="selected" class="admin-panel panel-content references">
        <h2>{{ t("引用关系") }}</h2>
        <p v-for="reference in (selected.references as Record<string,unknown>[])" :key="JSON.stringify(reference)">{{ reference.kind }} · {{ reference.id }} · {{ reference.role }}</p>
        <p v-if="!(selected.references as unknown[])?.length">{{ t("暂无业务引用") }}</p>
      </section>
    </AdminTableState>
  </div>
</template>

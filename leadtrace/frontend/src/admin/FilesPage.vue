<script setup lang="ts">
import { statusLabel } from "../i18n/status";
import { t, locale } from "../i18n";
import { onMounted, ref } from "vue";
import { ApiError } from "../api/client";
import { fetchAdminFiles, fetchFileReferences } from "./api";
import AdminTableState from "./AdminTableState.vue";
const files = ref<Record<string, unknown>[]>([]); const selected = ref<Record<string, unknown> | null>(null); const loading = ref(true); const error = ref<string | null>(null);
async function load(){try{files.value=await fetchAdminFiles()}catch(e){error.value="文件列表未能读取。"}finally{loading.value=false}}
async function inspect(file:Record<string,unknown>){try{selected.value=await fetchFileReferences(String(file.id))}catch{error.value="文件引用未能读取。"}}
onMounted(load);
</script>
<template>
  <div class="admin-page review-workspace">
    <header class="page-heading"><div><p class="eyebrow">ASSET REGISTRY</p><h1>{{ t("文件管理") }}</h1><p>{{ t("按完整性、访问级别和业务反向引用检查托管文件。") }}</p></div></header>
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
      <section v-if="selected" class="admin-panel panel-content references">
        <h2>{{ t("引用关系") }}</h2>
        <p v-for="reference in (selected.references as Record<string,unknown>[])" :key="JSON.stringify(reference)">{{ reference.kind }} · {{ reference.id }} · {{ reference.role }}</p>
        <p v-if="!(selected.references as unknown[])?.length">{{ t("暂无业务引用") }}</p>
      </section>
    </AdminTableState>
  </div>
</template>

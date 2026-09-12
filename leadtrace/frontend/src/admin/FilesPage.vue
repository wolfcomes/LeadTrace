<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ApiError } from "../api/client";
import { fetchAdminFiles, fetchFileReferences } from "./api";
import AdminTableState from "./AdminTableState.vue";
const files = ref<Record<string, unknown>[]>([]); const selected = ref<Record<string, unknown> | null>(null); const loading = ref(true); const error = ref<string | null>(null);
async function load(){try{files.value=await fetchAdminFiles()}catch(e){error.value=e instanceof ApiError?e.message:"请稍后重试。"}finally{loading.value=false}}
async function inspect(file:Record<string,unknown>){try{selected.value=await fetchFileReferences(String(file.id))}catch{error.value="文件引用未能读取。"}}
onMounted(load);
</script>
<template><div class="admin-page"><header class="page-heading"><div><p class="eyebrow">ASSET REGISTRY</p><h1>文件管理</h1><p>按完整性、访问级别和业务反向引用检查托管文件。</p></div></header><AdminTableState :loading="loading" :error="error"><section class="admin-panel"><table><thead><tr><th>文件</th><th>分类</th><th>完整性</th><th>大小</th><th>引用</th></tr></thead><tbody><tr v-for="file in files" :key="String(file.id)"><td>{{ file.filename }}</td><td>{{ file.category }}</td><td>{{ file.integrity }}</td><td>{{ file.byte_size }}</td><td><button type="button" @click="inspect(file)">查看反向引用</button></td></tr><tr v-if="files.length===0"><td colspan="5" class="empty">暂无托管文件</td></tr></tbody></table></section><section v-if="selected" class="admin-panel references"><h2>引用关系</h2><p v-for="reference in (selected.references as Record<string,unknown>[])" :key="JSON.stringify(reference)">{{ reference.kind }} · {{ reference.id }} · {{ reference.role }}</p><p v-if="!(selected.references as unknown[])?.length">暂无业务引用</p></section></AdminTableState></div></template>
<style scoped>.admin-page{padding:clamp(24px,4vw,52px)}.admin-panel{padding:20px;border:1px solid var(--line);background:#fff;overflow:auto}table{width:100%;border-collapse:collapse;font-size:.78rem}th,td{padding:13px 12px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}th{color:var(--ink-500);font-size:.68rem}.admin-panel button{padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:white;color:var(--ink-700);cursor:pointer}.references{margin-top:18px}.references h2{margin:0 0 12px;font:600 1.2rem Georgia,serif}.empty{padding:24px;text-align:center;color:var(--ink-500)}</style>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import type { Changeset } from "../api/schema";
import { ApiError } from "../api/client";
import { fetchChangesets } from "../review/api";
import {
  exportRelease,
  createReleaseOperationKey,
  fetchReleases,
  previewRelease,
  publishChangeset,
  validateRelease,
  type AdminRelease,
  type ReleasePreview,
} from "./api";

const releases = ref<AdminRelease[]>([]);
const changesets = ref<Changeset[]>([]);
const selectedChangeset = ref("");
const title = ref("");
const notes = ref("");
const loading = ref(true);
const busy = ref(false);
const error = ref<string | null>(null);
const result = ref<Record<string, unknown> | null>(null);
const preview = ref<ReleasePreview | null>(null);
const previewLoading = ref(false);
const publishKey = ref(createReleaseOperationKey("publish"));

const approved = computed(() => changesets.value.filter((entry) => entry.workflow_state === "approved"));

function requestReference(caught: ApiError): string {
  return caught.requestId ? ` 请求编号：${caught.requestId}` : "";
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    [releases.value, changesets.value] = await Promise.all([fetchReleases(), fetchChangesets()]);
    if (!selectedChangeset.value) selectedChangeset.value = approved.value[0]?.id ?? "";
  } catch {
    error.value = "发布数据未能读取。";
  } finally {
    loading.value = false;
  }
}

async function loadPreview(changesetId: string): Promise<void> {
  preview.value = null;
  if (!changesetId) return;
  previewLoading.value = true;
  error.value = null;
  try {
    preview.value = await previewRelease(changesetId);
  } catch {
    error.value = "发布候选校验未能完成。";
  } finally {
    previewLoading.value = false;
  }
}

watch(selectedChangeset, (changesetId) => {
  publishKey.value = createReleaseOperationKey("publish");
  void loadPreview(changesetId);
});

async function publish(): Promise<void> {
  if (!selectedChangeset.value) return;
  busy.value = true;
  error.value = null;
  try {
    result.value = await publishChangeset(
      {
        changeset_id: selectedChangeset.value,
        title: title.value.trim() || undefined,
        notes: notes.value.trim(),
      },
      publishKey.value,
    );
    publishKey.value = createReleaseOperationKey("publish");
    await load();
  } catch (caught) {
    if (caught instanceof ApiError && caught.kind === "conflict") {
      error.value = `发布候选已经发生变化，请重新核对后再次发布。${requestReference(caught)}`;
    } else if (caught instanceof ApiError && caught.kind === "validation") {
      error.value = `发布校验未通过，当前版本保持不变。${requestReference(caught)}`;
    } else {
      error.value = `发布未能完成。当前版本保持不变。${
        caught instanceof ApiError ? requestReference(caught) : ""
      }`;
    }
  } finally {
    busy.value = false;
  }
}

async function inspect(release: AdminRelease, mode: "validation" | "export"): Promise<void> {
  busy.value = true;
  error.value = null;
  try {
    result.value = mode === "validation"
      ? await validateRelease(release.id)
      : await exportRelease(release.id);
  } catch {
    error.value = mode === "validation" ? "版本校验未能完成。" : "版本导出未能生成。";
  } finally {
    busy.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="release-page">
    <header class="page-heading">
      <div><p class="eyebrow">ATOMIC PUBLICATION</p><h1>发布管理</h1><p>将已批准修改集原子发布，并保留确定性导出和历史回滚入口。</p></div>
      <RouterLink class="button-secondary" to="/admin/releases/rollback">回滚</RouterLink>
    </header>
    <p v-if="error" class="message" role="alert">{{ error }}</p>

    <section class="publish-band">
      <div><p class="eyebrow">APPROVED CHANGESET</p><h2>创建发布版本</h2></div>
      <label>已批准修改集<select v-model="selectedChangeset" :disabled="busy"><option value="">请选择</option><option v-for="entry in approved" :key="entry.id" :value="entry.id">{{ entry.title }} · v{{ entry.version }}</option></select></label>
      <label>版本标题<input v-model="title" maxlength="255" placeholder="默认使用修改集标题"></label>
      <label class="notes">发布说明<textarea v-model="notes" rows="3" placeholder="记录本次发布范围与核查结论"></textarea></label>
      <button data-publish-release class="button-primary" type="button" :disabled="busy || previewLoading || !selectedChangeset || !preview?.validation.valid" @click="publish">原子发布</button>
    </section>

    <section v-if="selectedChangeset" class="preview-band" data-release-preview>
      <div class="section-heading"><h2>发布前核查</h2><span v-if="previewLoading">正在校验</span><span v-else-if="preview?.validation.valid" class="preview-valid">校验通过</span><span v-else class="preview-invalid">需要处理</span></div>
      <div v-if="preview" class="delta-grid">
        <div><span>新增</span><strong>{{ preview.counts.create }}</strong></div>
        <div><span>更新</span><strong>{{ preview.counts.update }}</strong></div>
        <div><span>删除</span><strong>{{ preview.counts.tombstone }}</strong></div>
        <div><span>关联资产</span><strong>{{ preview.affected_asset_ids.length }}</strong></div>
      </div>
      <ul v-if="preview?.validation.issues.length" class="validation-list">
        <li v-for="(issue, index) in preview.validation.issues" :key="index">{{ issue.message || issue.code }}</li>
      </ul>
    </section>

    <section class="release-list">
      <div class="section-heading"><h2>版本历史</h2><span>{{ releases.length }} 个版本</span></div>
      <table>
        <thead><tr><th>版本</th><th>标题</th><th>发布时间</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="release in releases" :key="release.id">
            <td><code>{{ release.release_key }}</code></td><td>{{ release.title }}</td><td>{{ release.published_at }}</td><td><span :class="['state', { current: release.is_current }]">{{ release.is_current ? "当前版本" : "历史版本" }}</span></td>
            <td class="actions"><button type="button" :disabled="busy" @click="inspect(release, 'validation')">重新校验</button><button type="button" :disabled="busy" @click="inspect(release, 'export')">导出清单</button></td>
          </tr>
          <tr v-if="!loading && releases.length === 0"><td colspan="5" class="empty">暂无发布版本</td></tr>
        </tbody>
      </table>
    </section>

    <section v-if="result" class="result-panel"><div class="section-heading"><h2>操作结果</h2><button type="button" title="关闭结果" @click="result = null">关闭</button></div><pre>{{ JSON.stringify(result, null, 2) }}</pre></section>
  </div>
</template>

<style scoped>
.release-page{padding:clamp(24px,4vw,52px)}.page-heading>a{text-decoration:none}.message{padding:11px 14px;border-left:3px solid var(--danger);color:var(--danger);background:#fff;font-size:.76rem}.publish-band{display:grid;grid-template-columns:minmax(180px,.7fr) minmax(210px,1fr) minmax(190px,.8fr);gap:14px;align-items:end;margin-bottom:14px;padding:20px;border:1px solid var(--line);background:#fff}.publish-band h2,.section-heading h2{margin:0;font:600 1.15rem/1.3 Georgia,"Noto Serif SC Variable",serif}.publish-band label{display:grid;gap:7px;color:var(--ink-650);font-size:.68rem;font-weight:700}.publish-band input,.publish-band select,.publish-band textarea{width:100%;min-height:39px;padding:8px 10px;border:1px solid var(--line);border-radius:6px;background:#fff;font:inherit}.publish-band .notes{grid-column:2/4}.preview-band,.release-list,.result-panel{padding:20px;border:1px solid var(--line);background:#fff;overflow:auto}.preview-band{margin-bottom:22px}.preview-valid{color:var(--forest-800)!important}.preview-invalid{color:var(--danger)!important}.delta-grid{display:grid;grid-template-columns:repeat(4,minmax(100px,1fr));border:1px solid var(--line)}.delta-grid>div{display:grid;gap:5px;padding:12px;border-right:1px solid var(--line)}.delta-grid>div:last-child{border-right:0}.delta-grid span{color:var(--ink-500);font-size:.65rem}.delta-grid strong{font-size:1.1rem}.validation-list{margin:12px 0 0;padding-left:20px;color:var(--danger);font-size:.72rem}.section-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:14px}.section-heading span{color:var(--ink-500);font-size:.7rem}table{width:100%;border-collapse:collapse;font-size:.75rem}th,td{padding:12px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}th{color:var(--ink-500);font-size:.65rem}.state{padding:4px 7px;border-radius:5px;color:var(--ink-600);background:var(--canvas);font-size:.64rem}.state.current{color:var(--forest-800);background:var(--forest-100)}.actions{display:flex;gap:7px}.actions button,.section-heading button{padding:6px 9px;border:1px solid var(--line);border-radius:6px;color:var(--ink-700);background:#fff;cursor:pointer}.empty{text-align:center;color:var(--ink-500)}.result-panel{margin-top:18px}.result-panel pre{max-height:360px;margin:0;padding:14px;overflow:auto;background:var(--canvas);font-size:.68rem}@media(max-width:900px){.publish-band,.delta-grid{grid-template-columns:1fr}.publish-band .notes{grid-column:auto}.delta-grid>div{border-right:0;border-bottom:1px solid var(--line)}.delta-grid>div:last-child{border-bottom:0}}
</style>

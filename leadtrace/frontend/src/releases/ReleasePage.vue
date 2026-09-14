<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import type { Changeset } from "../api/schema";
import { ApiError } from "../api/client";
import {
  fetchImportCandidates,
  type ImportCandidate,
} from "../admin/api";
import { fetchChangesets } from "../review/api";
import {
  exportRelease,
  createReleaseOperationKey,
  fetchReleases,
  previewRelease,
  publishBaseline,
  publishChangeset,
  validateRelease,
  type AdminRelease,
  type ReleasePreview,
} from "./api";

const route = useRoute();
const releases = ref<AdminRelease[]>([]);
const changesets = ref<Changeset[]>([]);
const candidates = ref<ImportCandidate[]>([]);
const selectedChangeset = ref("");
const selectedBaseline = ref("");
const title = ref("");
const notes = ref("");
const baselineTitle = ref("");
const baselineNotes = ref("");
const loading = ref(true);
const busy = ref(false);
const error = ref<string | null>(null);
const result = ref<Record<string, unknown> | null>(null);
const preview = ref<ReleasePreview | null>(null);
const previewLoading = ref(false);
const publishKey = ref(createReleaseOperationKey("publish"));
const baselinePublishKey = ref(createReleaseOperationKey("baseline"));

const approved = computed(() => changesets.value.filter((entry) => entry.workflow_state === "approved"));
const approvedBaselines = computed(() => candidates.value.filter((entry) => entry.status === "approved"));
const selectedBaselineCandidate = computed(() => (
  approvedBaselines.value.find((entry) => entry.id === selectedBaseline.value) ?? null
));

function formatCount(value: number | undefined): string {
  return value?.toLocaleString("zh-CN") ?? "-";
}

function requestReference(caught: ApiError): string {
  return caught.requestId ? ` 请求编号：${caught.requestId}` : "";
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    const [releaseData, candidateData] = await Promise.allSettled([
      Promise.all([fetchReleases(), fetchChangesets()]),
      fetchImportCandidates(),
    ]);
    if (releaseData.status === "rejected") {
      error.value = "发布数据未能读取。";
      return;
    }
    [releases.value, changesets.value] = releaseData.value;
    if (candidateData.status === "fulfilled") {
      candidates.value = candidateData.value;
    } else {
      candidates.value = [];
      error.value = "首次发布候选未能读取，修改集发布仍可使用。";
    }
    if (!selectedChangeset.value) selectedChangeset.value = approved.value[0]?.id ?? "";
    if (!approvedBaselines.value.some((entry) => entry.id === selectedBaseline.value)) {
      const queryCandidate = typeof route.query.candidate === "string"
        ? route.query.candidate
        : "";
      selectedBaseline.value = approvedBaselines.value.some(
        (entry) => entry.id === queryCandidate,
      ) ? queryCandidate : approvedBaselines.value[0]?.id ?? "";
    }
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

watch(selectedBaseline, () => {
  baselinePublishKey.value = createReleaseOperationKey("baseline");
});

async function publishInitialBaseline(): Promise<void> {
  if (!selectedBaseline.value) return;
  busy.value = true;
  error.value = null;
  try {
    result.value = await publishBaseline(
      {
        candidate_id: selectedBaseline.value,
        title: baselineTitle.value.trim() || undefined,
        notes: baselineNotes.value.trim(),
      },
      baselinePublishKey.value,
    );
    baselinePublishKey.value = createReleaseOperationKey("baseline");
    await load();
  } catch (caught) {
    if (caught instanceof ApiError && caught.kind === "conflict") {
      error.value = `首次发布候选已经变化，当前版本保持不变。${requestReference(caught)}`;
    } else if (caught instanceof ApiError && caught.kind === "validation") {
      error.value = `首次发布校验未通过，当前版本保持不变。${requestReference(caught)}`;
    } else {
      error.value = `首次发布未能完成，当前版本保持不变。${
        caught instanceof ApiError ? requestReference(caught) : ""
      }`;
    }
  } finally {
    busy.value = false;
  }
}

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
  <div class="release-page admin-page review-workspace">
    <header class="page-heading">
      <div><p class="eyebrow">ATOMIC PUBLICATION</p><h1>发布管理</h1><p>将已批准修改集原子发布，并保留确定性导出和历史回滚入口。</p></div>
      <RouterLink class="button-secondary" to="/admin/releases/rollback">回滚</RouterLink>
    </header>
    <p v-if="error" class="message inline-feedback is-error" role="alert">{{ error }}</p>

    <section
      v-if="approvedBaselines.length"
      class="publish-band baseline-band panel"
      data-baseline-publication
    >
      <div>
        <p class="eyebrow">APPROVED BASELINE</p>
        <h2>首次发布</h2>
        <span class="baseline-state status-chip is-approved">已批准，待发布</span>
      </div>
      <label class="form-field">
        已批准导入候选
        <select v-model="selectedBaseline" class="form-control" :disabled="busy">
          <option v-for="candidate in approvedBaselines" :key="candidate.id" :value="candidate.id">
            {{ candidate.id }}
          </option>
        </select>
      </label>
      <label class="form-field">
        版本标题
        <input v-model="baselineTitle" class="form-control" maxlength="255" placeholder="LeadTrace initial baseline">
      </label>
      <div v-if="selectedBaselineCandidate" class="baseline-summary">
        <span>文献 <strong>{{ formatCount(selectedBaselineCandidate.manifest.counts?.corpus_papers as number | undefined) }}</strong></span>
        <span>修订 <strong>{{ formatCount(selectedBaselineCandidate.manifest.revision_count) }}</strong></span>
        <span><strong>{{ formatCount(selectedBaselineCandidate.manifest.asset_linkage?.resolved_references) }}</strong> 解析引用</span>
        <span><strong>{{ formatCount(selectedBaselineCandidate.manifest.asset_linkage?.unique_resolved_assets) }}</strong> 唯一资产</span>
        <span><strong>{{ formatCount(selectedBaselineCandidate.manifest.asset_linkage?.missing_references) }}</strong> 缺失</span>
        <span><strong>{{ formatCount(selectedBaselineCandidate.manifest.asset_linkage?.ambiguous_references) }}</strong> 歧义</span>
        <span><strong>{{ formatCount(selectedBaselineCandidate.manifest.asset_linkage?.corrupt_references) }}</strong> 损坏</span>
      </div>
      <label class="notes form-field">
        发布说明
        <textarea v-model="baselineNotes" class="form-control" rows="3" maxlength="4000" placeholder="记录首次发布核查结论" />
      </label>
      <button
        data-publish-baseline
        class="button-primary"
        type="button"
        :disabled="busy || !selectedBaseline"
        @click="publishInitialBaseline"
      >发布初始版本</button>
    </section>

    <section class="publish-band panel">
      <div><p class="eyebrow">APPROVED CHANGESET</p><h2>创建发布版本</h2></div>
      <label class="form-field">已批准修改集<select v-model="selectedChangeset" class="form-control" :disabled="busy"><option value="">请选择</option><option v-for="entry in approved" :key="entry.id" :value="entry.id">{{ entry.title }} · v{{ entry.version }}</option></select></label>
      <label class="form-field">版本标题<input v-model="title" class="form-control" maxlength="255" placeholder="默认使用修改集标题"></label>
      <label class="notes form-field">发布说明<textarea v-model="notes" class="form-control" rows="3" placeholder="记录本次发布范围与核查结论"></textarea></label>
      <button data-publish-release class="button-primary" type="button" :disabled="busy || previewLoading || !selectedChangeset || !preview?.validation.valid" @click="publish">原子发布</button>
    </section>

    <section v-if="selectedChangeset" class="preview-band panel" data-release-preview>
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

    <section class="release-list panel table-wrap">
      <div class="section-heading"><h2>版本历史</h2><span>{{ releases.length }} 个版本</span></div>
      <table class="data-table">
        <thead><tr><th>版本</th><th>标题</th><th>发布时间</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="release in releases" :key="release.id">
            <td><code>{{ release.release_key }}</code></td><td>{{ release.title }}</td><td>{{ release.published_at }}</td><td><span :class="['state', 'status-chip', { 'is-ok': release.is_current }]">{{ release.is_current ? "当前版本" : "历史版本" }}</span></td>
            <td class="actions table-actions"><button class="button-secondary" type="button" :disabled="busy" @click="inspect(release, 'validation')">重新校验</button><button class="button-secondary" type="button" :disabled="busy" @click="inspect(release, 'export')">导出清单</button></td>
          </tr>
          <tr v-if="!loading && releases.length === 0"><td colspan="5" class="empty">暂无发布版本</td></tr>
        </tbody>
      </table>
    </section>

    <section v-if="result" class="result-panel panel"><div class="section-heading"><h2>操作结果</h2><button class="button-secondary" type="button" title="关闭结果" @click="result = null">关闭</button></div><pre>{{ JSON.stringify(result, null, 2) }}</pre></section>
  </div>
</template>

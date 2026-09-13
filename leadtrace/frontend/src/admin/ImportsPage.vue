<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";

import {
  applyImport,
  decideImportCandidate,
  dryRunImport,
  fetchAdminImports,
  fetchImportCandidates,
  type ImportCandidate,
} from "./api";

const imports = ref<Record<string, unknown>[]>([]);
const candidates = ref<ImportCandidate[]>([]);
const sourceRoot = ref("baseline");
const report = ref<Record<string, unknown> | null>(null);
const busy = ref(false);
const decisionBusy = ref<string | null>(null);
const decisionReasons = reactive<Record<string, string>>({});
const error = ref<string | null>(null);

const stateLabels: Record<ImportCandidate["status"], string> = {
  imported_baseline: "待审批",
  approved: "已批准，待发布",
  rejected: "已拒绝",
  published: "已发布",
};

function manifestValue(
  candidate: ImportCandidate,
  section: "counts" | "integrity" | "asset_linkage",
  key: string,
): string {
  const values = candidate.manifest[section] as Readonly<Record<string, unknown>> | undefined;
  const value = values?.[key];
  return typeof value === "number" ? value.toLocaleString("zh-CN") : "-";
}

async function load(): Promise<void> {
  error.value = null;
  try {
    [imports.value, candidates.value] = await Promise.all([
      fetchAdminImports(),
      fetchImportCandidates(),
    ]);
  } catch {
    error.value = "导入记录未能读取。";
  }
}

async function preview(): Promise<void> {
  busy.value = true;
  error.value = null;
  try {
    report.value = await dryRunImport(sourceRoot.value);
  } catch {
    error.value = "预检失败，请检查来源配置。";
  } finally {
    busy.value = false;
  }
}

async function apply(): Promise<void> {
  busy.value = true;
  error.value = null;
  try {
    report.value = await applyImport(sourceRoot.value);
    await load();
  } catch {
    error.value = "导入未能应用。";
  } finally {
    busy.value = false;
  }
}

async function decide(
  candidate: ImportCandidate,
  action: "approve" | "reject",
): Promise<void> {
  const reason = (decisionReasons[candidate.id] ?? "").trim();
  if (!reason) return;
  decisionBusy.value = candidate.id;
  error.value = null;
  try {
    const updated = await decideImportCandidate(candidate.id, action, reason);
    const index = candidates.value.findIndex((entry) => entry.id === candidate.id);
    if (index >= 0) candidates.value[index] = updated;
    delete decisionReasons[candidate.id];
  } catch {
    error.value = "审批决定未能保存，候选状态保持不变。";
  } finally {
    decisionBusy.value = null;
  }
}

onMounted(load);
</script>

<template>
  <div class="admin-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">STAGED INGESTION</p>
        <h1>导入管理</h1>
        <p>管理基线预检、导入批次和首次发布候选的独立审批状态。</p>
      </div>
    </header>

    <p v-if="error" class="message" role="alert">{{ error }}</p>

    <section class="admin-panel import-controls">
      <label for="source-root">来源配置</label>
      <input id="source-root" v-model="sourceRoot" autocomplete="off">
      <button class="button-secondary" type="button" :disabled="busy" @click="preview">预检</button>
      <button class="button-primary" type="button" :disabled="busy" @click="apply">应用到 staging</button>
    </section>

    <section v-if="report" class="admin-panel">
      <h2>预检结果</h2>
      <pre>{{ JSON.stringify(report, null, 2) }}</pre>
    </section>

    <section class="admin-panel candidate-panel">
      <div class="section-heading">
        <h2>首次发布候选</h2>
        <span>{{ candidates.length }} 个候选</span>
      </div>
      <table>
        <thead>
          <tr>
            <th>状态</th>
            <th>来源指纹</th>
            <th>文献 / 修订</th>
            <th>资产</th>
            <th>完整性</th>
            <th>审批</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="candidate in candidates" :key="candidate.id">
            <td>
              <span :class="['candidate-state', `state-${candidate.status}`]">
                {{ stateLabels[candidate.status] }}
              </span>
            </td>
            <td>
              <code class="fingerprint" :title="candidate.manifest.source_fingerprint">
                {{ candidate.manifest.source_fingerprint }}
              </code>
            </td>
            <td>
              {{ manifestValue(candidate, "counts", "corpus_papers") }} /
              {{ candidate.manifest.revision_count?.toLocaleString("zh-CN") ?? "-" }}
            </td>
            <td>
              {{ manifestValue(candidate, "asset_linkage", "resolved_references") }} 解析引用<br>
              <small>
                {{ manifestValue(candidate, "asset_linkage", "unique_resolved_assets") }} 唯一资产 ·
                {{ manifestValue(candidate, "asset_linkage", "missing_references") }} 缺失 ·
                {{ manifestValue(candidate, "asset_linkage", "ambiguous_references") }} 歧义 ·
                {{ manifestValue(candidate, "asset_linkage", "corrupt_references") }} 损坏
              </small>
            </td>
            <td>
              <span v-if="manifestValue(candidate, 'integrity', 'dangling_entity_references') === '0'" class="integrity-ok">通过</span>
              <span v-else>需核查</span>
            </td>
            <td class="decision-cell">
              <template v-if="candidate.status === 'imported_baseline'">
                <label :for="`candidate-reason-${candidate.id}`">审批原因</label>
                <textarea
                  :id="`candidate-reason-${candidate.id}`"
                  v-model="decisionReasons[candidate.id]"
                  :data-candidate-reason="candidate.id"
                  rows="2"
                  maxlength="4000"
                />
                <div class="decision-actions">
                  <button
                    data-candidate-decision
                    :data-candidate-approve="candidate.id"
                    class="button-primary"
                    type="button"
                    :disabled="decisionBusy === candidate.id || !(decisionReasons[candidate.id] ?? '').trim()"
                    @click="decide(candidate, 'approve')"
                  >批准</button>
                  <button
                    data-candidate-decision
                    :data-candidate-reject="candidate.id"
                    class="button-danger"
                    type="button"
                    :disabled="decisionBusy === candidate.id || !(decisionReasons[candidate.id] ?? '').trim()"
                    @click="decide(candidate, 'reject')"
                  >拒绝</button>
                </div>
              </template>
              <RouterLink
                v-else-if="candidate.status === 'approved'"
                class="button-primary publish-link"
                :data-candidate-publish="candidate.id"
                :to="{ path: '/admin/releases', query: { candidate: candidate.id } }"
              >进入首次发布</RouterLink>
              <div v-else-if="candidate.decision" class="decision-record">
                <strong>{{ candidate.decision.decision === "approve" ? "批准" : "拒绝" }}</strong>
                <span>{{ candidate.decision.reason }}</span>
              </div>
            </td>
          </tr>
          <tr v-if="candidates.length === 0">
            <td colspan="6" class="empty">暂无首次发布候选</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="admin-panel">
      <div class="section-heading">
        <h2>导入批次</h2>
        <span>{{ imports.length }} 个批次</span>
      </div>
      <table>
        <thead><tr><th>状态</th><th>指纹</th><th>开始时间</th></tr></thead>
        <tbody>
          <tr v-for="item in imports" :key="String(item.id)">
            <td>{{ item.status }}</td>
            <td><code class="fingerprint">{{ item.source_fingerprint }}</code></td>
            <td>{{ item.started_at }}</td>
          </tr>
          <tr v-if="imports.length === 0"><td colspan="3" class="empty">暂无导入批次</td></tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<style scoped>
.admin-page{padding:clamp(24px,4vw,52px)}
.admin-panel{margin-bottom:18px;padding:20px;border:1px solid var(--line);background:#fff;overflow:auto}
.message{margin:0 0 14px;padding:11px 14px;border-left:3px solid var(--danger);color:var(--danger);background:#fff;font-size:.76rem}
.import-controls{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.import-controls label,.decision-cell label{font-size:.68rem;font-weight:700;color:var(--ink-650)}
.import-controls input,.decision-cell textarea{min-height:38px;padding:7px 10px;border:1px solid var(--line);border-radius:6px;background:#fff;font:inherit}
.section-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:14px}
.section-heading span{color:var(--ink-500);font-size:.7rem}
h2{margin:0;font:600 1.15rem Georgia,"Noto Serif SC Variable",serif}
pre{max-height:280px;overflow:auto;background:var(--canvas);padding:14px;font-size:.72rem}
table{width:100%;min-width:820px;border-collapse:collapse;font-size:.75rem}
th,td{padding:12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--ink-500);font-size:.65rem;white-space:nowrap}
.fingerprint{display:block;max-width:190px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.candidate-state{display:inline-block;padding:4px 7px;border-radius:5px;background:var(--canvas);white-space:nowrap;font-size:.64rem}
.state-approved,.state-published,.integrity-ok{color:var(--forest-800)}
.state-rejected{color:var(--danger)}
.decision-cell{min-width:240px}
.decision-cell textarea{display:block;width:100%;margin:6px 0;resize:vertical}
.decision-actions{display:flex;gap:7px}
.decision-actions button{min-width:64px}
.publish-link{display:inline-block;text-decoration:none;white-space:nowrap}
.decision-record{display:grid;gap:5px;max-width:280px}
.decision-record span,td small{color:var(--ink-500);font-size:.66rem;white-space:normal}
.empty{text-align:center;color:var(--ink-500)}
@media(max-width:760px){.admin-page{padding:20px 14px}.admin-panel{padding:14px}.import-controls{align-items:stretch}.import-controls input{flex:1 1 100%}}
</style>

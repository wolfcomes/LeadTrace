<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { lineageTypeLabels } from "../v2/types";
import { ApiError } from "../api/client";
import { useAuthStore } from "../auth/store";
import { decideSubmission, getAdminSubmission } from "../v2/api";
import type { AdminSubmissionDetail, DecisionMutation } from "../v2/types";
import SubmissionDiff from "./SubmissionDiff.vue";

type State = "loading" | "ready" | "not-found" | "error";
const route = useRoute();
const auth = useAuthStore();
const state = ref<State>("loading");
const detail = ref<AdminSubmissionDetail | null>(null);
const reason = ref("");
const acting = ref<"approve" | "request_changes" | null>(null);
const decision = ref<DecisionMutation | null>(null);
const error = ref<string | null>(null);
const snapshot = computed(() => detail.value?.submission.snapshot ?? null);
const compoundLabels = computed(() => new Map(snapshot.value?.compounds.map((compound) => [compound.id, compound.compound_label]) ?? []));
const sourceImagesByCompound = computed(() => {
  const grouped = new Map<string, NonNullable<typeof snapshot.value>["structure_source_images"]>();
  for (const image of snapshot.value?.structure_source_images ?? []) {
    const current = grouped.get(image.compound_id) ?? [];
    current.push(image);
    grouped.set(image.compound_id, current);
  }
  return grouped;
});
const decisionDisabled = computed(() => !detail.value || !reason.value.trim() || acting.value !== null || decision.value !== null);

function adminAssetUrl(assetId: string): string {
  return `/api/v1/assets/${encodeURIComponent(assetId)}/content`;
}
function sourceImageUrl(sourceImageId: string): string {
  return `/api/v2/structure-source-images/${encodeURIComponent(sourceImageId)}/content`;
}
function sourcePdfUrl(page?: number): string {
  const base = `/api/v2/papers/${encodeURIComponent(String(detail.value?.submission.paper_id ?? ""))}/source-pdf`;
  return page ? `${base}#page=${page}` : base;
}
function edgeLabel(edgeId: string): string {
  const edge = snapshot.value?.lineage_edges.find((item) => item.id === edgeId);
  return edge
    ? `${compoundLabels.value.get(edge.parent_compound_id) ?? edge.parent_compound_id} → ${compoundLabels.value.get(edge.child_compound_id) ?? edge.child_compound_id}`
    : edgeId;
}
function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Shanghai" }).format(new Date(value));
}
async function load(): Promise<void> {
  state.value = "loading";
  detail.value = null;
  decision.value = null;
  error.value = null;
  try {
    detail.value = await getAdminSubmission(String(route.params.submissionId ?? ""));
    state.value = "ready";
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 404) state.value = "not-found";
    else {
      state.value = "error";
      error.value = caught instanceof ApiError ? `Submission 未能读取。请求编号：${caught.requestId ?? "未知"}` : "Submission 未能读取。";
    }
  }
}
async function decide(action: "approve" | "request_changes"): Promise<void> {
  if (!detail.value || !reason.value.trim() || acting.value || decision.value) return;
  acting.value = action;
  error.value = null;
  const current = detail.value.submission;
  try {
    decision.value = await decideSubmission(current.id, { content_hash: current.content_hash, action, reason: reason.value.trim() }, `${action}-${current.id}-${current.content_hash}`, auth.csrfToken);
  } catch (caught) {
    error.value = caught instanceof ApiError && caught.kind === "conflict" ? "Submission 状态或内容哈希已经变化，请返回队列后重新核对。" : "审批决定未能保存。";
  } finally {
    acting.value = null;
  }
}
watch(() => route.params.submissionId, load, { immediate: true });
</script>

<template>
  <div class="admin-page submission-review-page" data-submission-review>
    <RouterLink class="back-link" :to="{ name: 'admin-submissions' }">← 返回提交审批</RouterLink>
    <section v-if="state === 'loading'" class="page-state" aria-live="polite">正在读取冻结 Submission…</section>
    <section v-else-if="state === 'not-found'" class="page-state"><span class="state-symbol" aria-hidden="true">404</span><h1>未找到待审批 Submission</h1></section>
    <section v-else-if="state === 'error'" class="page-state" role="alert"><span class="state-symbol is-error" aria-hidden="true">!</span><h1>{{ error }}</h1><button class="button-secondary" type="button" @click="load">重新加载</button></section>
    <template v-else-if="detail && snapshot">
      <header class="page-heading">
        <div><p class="eyebrow">IMMUTABLE SUBMISSION · #{{ detail.submission.submission_number }}</p><h1>{{ detail.bibliography.title }}</h1><p>{{ detail.bibliography.journal }} · {{ detail.bibliography.publication_year }} · {{ detail.bibliography.volume }}({{ detail.bibliography.issue }})</p><a class="button-secondary source-pdf-link" data-source-pdf :href="sourcePdfUrl()" target="_blank" rel="noopener">打开 Source PDF ↗</a></div>
        <dl class="submission-identity"><div><dt>Paper</dt><dd><code>{{ detail.bibliography.paper_key }}</code></dd></div><div><dt>Content hash</dt><dd><code>{{ detail.submission.content_hash }}</code></dd></div><div><dt>提交时间</dt><dd>{{ formatDate(detail.submission.submitted_at) }}</dd></div></dl>
      </header>
      <p v-if="detail.submission.reviewer_note" class="reviewer-attestation panel"><strong>Reviewer 声明</strong><span>{{ detail.submission.reviewer_note }}</span></p>
      <p v-if="error" class="message inline-feedback is-error" role="alert">{{ error }}</p>
      <section class="submission-science panel" data-structure-comparison>
        <div class="section-heading"><div><p class="eyebrow">STRUCTURE VERIFICATION</p><h2>结构原图与 RDKit 对照</h2></div></div>
        <div class="submission-structure-grid">
          <article v-for="structure in snapshot.structures" :key="structure.id">
            <header><strong>{{ compoundLabels.get(structure.compound_id) ?? structure.compound_id }}</strong><span class="status-chip">{{ structure.status }}</span></header>
            <div class="submission-image-pair">
              <div v-for="image in sourceImagesByCompound.get(structure.compound_id) ?? []" :key="image.id"><span>PDF 原图 · 第 {{ image.page_number }} 页</span><img v-if="image.crop_asset_id" data-structure-source-image :src="sourceImageUrl(image.id)" alt="PDF 结构原图"><a :href="sourcePdfUrl(image.page_number)" target="_blank" rel="noopener">在 PDF 中核对 ↗</a><p v-if="!image.crop_asset_id">Crop 尚不可用</p></div>
              <div><span>RDKit 重绘</span><img v-if="structure.depiction_asset_id" data-rdkit-depiction :src="adminAssetUrl(structure.depiction_asset_id)" alt="RDKit 结构重绘"><code v-else>{{ structure.canonical_smiles ?? structure.smiles ?? "—" }}</code></div>
            </div>
            <code>{{ structure.canonical_smiles ?? structure.smiles ?? "—" }}</code>
          </article>
        </div>
      </section>
      <section class="submission-science panel" data-submission-lineage>
        <div class="section-heading"><div><p class="eyebrow">LINEAGE</p><h2>完整 Lineage</h2></div></div>
        <article v-for="lineage in snapshot.lineages" :key="lineage.id" class="submission-lineage-card">
          <header><strong>{{ lineage.lineage_label }}</strong><span class="status-chip">{{ lineageTypeLabels[lineage.lineage_type] }}</span><span>{{ lineage.description }}</span></header>
          <div class="lineage-member-roles">
            <span v-for="member in snapshot.lineage_members.filter((item) => item.lineage_id === lineage.id)" :key="member.id"><strong>{{ compoundLabels.get(member.compound_id) }}</strong><small>{{ member.role }}</small></span>
          </div>
          <div v-for="edge in snapshot.lineage_edges.filter((item) => item.lineage_id === lineage.id)" :key="edge.id" class="submission-edge-row"><strong>{{ compoundLabels.get(edge.parent_compound_id) }} → {{ compoundLabels.get(edge.child_compound_id) }}</strong><span>{{ edge.relation_type }} · {{ edge.modification_summary ?? "—" }}</span></div>
        </article>
      </section>
      <section class="submission-science panel" data-submission-evidence>
        <div class="section-heading"><div><p class="eyebrow">EVIDENCE & ACTIVITY</p><h2>关系证据与活性</h2></div></div>
        <div class="submission-evidence-grid">
          <div>
            <article v-for="item in snapshot.evidence" :key="item.id" class="published-evidence-card">
              <header><strong>{{ item.kind }} · 第 {{ item.page_number }} 页</strong><span>{{ item.caption }}</span></header>
              <blockquote v-if="item.quoted_text">{{ item.quoted_text }}</blockquote>
              <a data-evidence-pdf-locator :href="sourcePdfUrl(item.page_number)" target="_blank" rel="noopener">在 Source PDF 第 {{ item.page_number }} 页核对 bbox ↗</a>
              <small v-for="link in snapshot.edge_evidence_links.filter((row) => row.evidence_id === item.id)" :key="link.id">{{ link.role }} · {{ edgeLabel(link.edge_id) }}</small>
            </article>
            <p v-if="!snapshot.evidence.length" class="section-empty">没有报告 Evidence。</p>
          </div>
          <div class="activity-table-wrap">
            <table v-if="snapshot.activities.length" class="data-table">
              <thead><tr><th>Compound</th><th>Assay</th><th>Metric</th><th>Value</th></tr></thead>
              <tbody><tr v-for="activity in snapshot.activities" :key="activity.id"><td>{{ compoundLabels.get(activity.compound_id) }}</td><td>{{ activity.assay_name }}</td><td>{{ activity.metric }}</td><td><strong>{{ activity.operator }} {{ activity.value }} {{ activity.unit ?? "" }}</strong></td></tr></tbody>
            </table>
            <p v-else class="section-empty">没有报告 Activity。</p>
          </div>
        </div>
      </section>
      <SubmissionDiff :events="detail.reviewer_diff" />
      <section class="decision-panel panel">
        <div class="section-heading"><div><p class="eyebrow">ADMIN DECISION</p><h2>审批决定</h2></div></div>
        <div v-if="decision" class="submission-success" data-decision-success>
          <strong>{{ decision.decision.action === 'approve' ? '已批准并发布' : '已退回 Reviewer 修改' }}</strong><p>{{ decision.decision.reason }}</p>
          <RouterLink v-if="decision.published_version" class="button-secondary" data-published-paper-link :to="{ name: 'paper-detail', params: { paperId: decision.published_version.paper_id } }">查看正式文章 →</RouterLink>
        </div>
        <template v-else>
          <label class="form-field"><span>决定理由（必填）</span><textarea v-model="reason" data-decision-reason rows="4" placeholder="记录批准依据，或明确需要 Reviewer 修改的内容。"></textarea></label>
          <div class="decision-actions"><button class="button-secondary" data-request-changes type="button" :disabled="decisionDisabled" @click="decide('request_changes')">退回修改</button><button class="button-primary" data-approve-submission type="button" :disabled="decisionDisabled" @click="decide('approve')">批准并发布</button></div>
        </template>
      </section>
    </template>
  </div>
</template>

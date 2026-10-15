<script setup lang="ts">
import AiProvenance from "../review/paper/AiProvenance.vue";
import HighlightCards from "../review/paper/HighlightCards.vue";
import ArticleMetadata from "../review/paper/ArticleMetadata.vue";
import ReviewHint from "../review/paper/ReviewHint.vue";
import { statusLabel } from "../i18n/status";
import { t, locale } from "../i18n";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { reviewVersionStatus } from './reviewVersionLabels';
import { lineageTypeLabels } from "../v2/types";
import { ApiError } from "../api/client";
import { useAuthStore } from "../auth/store";
import { decideSubmission, getAdminSubmission } from "../v2/api";
import type { AdminSubmissionDetail, DecisionMutation } from "../v2/types";
import SubmissionDiff from "./SubmissionDiff.vue";
import SubmissionComparison from "./SubmissionComparison.vue";
import FrozenSubmissionScope from "./FrozenSubmissionScope.vue";
import FrozenEvidence from "./FrozenEvidence.vue";

type State = "loading" | "ready" | "not-found" | "error";
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const state = ref<State>("loading");
const detail = ref<AdminSubmissionDetail | null>(null);
const fullContentOpen = ref(false);
const historyOpen = ref(false);
const reason = ref("");
const acting = ref<"approve" | "request_changes" | null>(null);
const decision = ref<DecisionMutation | null>(null);
const error = ref<string | null>(null);
const errorRequestId = ref<string>();
const supplementOpen = ref<Record<string, boolean>>({});
let loadSequence = 0;
const rounds = computed(() => detail.value?.review_rounds);
const versions = computed(() => rounds.value?.versions ?? []);
const selectedVersion = computed(() => versions.value.find(v => v.id === detail.value?.submission.id));
const selectedIndex = computed(() => versions.value.findIndex(v => v.id === detail.value?.submission.id));
const previousVersion = computed(() => versions.value[selectedIndex.value - 1]);
const nextVersion = computed(() => selectedIndex.value >= 0 ? versions.value[selectedIndex.value + 1] : undefined);
const canDecide = computed(() => rounds.value ? rounds.value.can_decide : true);
const snapshot = computed(() => detail.value?.submission.snapshot ?? null);
function highlightDepiction(compoundId: string): string | undefined {
  const asset = snapshot.value?.structures.find(s => s.compound_id === compoundId)?.depiction_asset_id;
  return asset ? adminAssetUrl(asset) : undefined;
}
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
const decisionDisabled = computed(() => !canDecide.value || !detail.value || !reason.value.trim() || acting.value !== null || decision.value !== null);

function chooseVersion(event: Event) {
  const id = (event.target as HTMLSelectElement).value;
  if (acting.value || !versions.value.some(v => v.id === id)) return;
  void router.push({ name: 'admin-submission-detail', params: { submissionId: id } });
}

function adminAssetUrl(assetId: string): string {
  return `/api/v1/assets/${encodeURIComponent(assetId)}/content`;
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
  return new Intl.DateTimeFormat(locale.value, { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Shanghai" }).format(new Date(value));
}
async function load(): Promise<void> {
  const sequence = ++loadSequence;
  const requestedId = String(route.params.submissionId ?? '');
  state.value = "loading";
  fullContentOpen.value = false;
  historyOpen.value = false;
  supplementOpen.value = {};
  reason.value = '';
  detail.value = null;
  decision.value = null;
  error.value = null;
  errorRequestId.value = undefined;
  try {
    const response = await getAdminSubmission(requestedId);
    if (sequence !== loadSequence) return;
    detail.value = response;
    state.value = "ready";
  } catch (caught) {
    if (sequence !== loadSequence) return;
    errorRequestId.value = caught instanceof ApiError ? caught.requestId : undefined;
    if (caught instanceof ApiError && caught.status === 404) state.value = "not-found";
    else {
      state.value = "error";
      error.value = caught instanceof ApiError ? "Submission 未能读取。" : "Submission 未能读取。";
    }
  }
}
async function decide(action: "approve" | "request_changes"): Promise<void> {
  if (!canDecide.value || !detail.value || !reason.value.trim() || acting.value || decision.value) return;
  const sequence = loadSequence;
  acting.value = action;
  error.value = null;
  const current = detail.value.submission;
  try {
    const result = await decideSubmission(current.id, { content_hash: current.content_hash, action, reason: reason.value.trim() }, `${action}-${current.id}-${current.content_hash}`, auth.csrfToken);
    if (sequence !== loadSequence) return;
    decision.value = result;
    const version = versions.value.find(v => v.id === current.id);
    if (version) { version.status = result.decision.action; version.decision = result.decision; }
    if (rounds.value) rounds.value.can_decide = false;
  } catch (caught) {
    if (sequence !== loadSequence) return;
    errorRequestId.value = caught instanceof ApiError ? caught.requestId : undefined;
    error.value = caught instanceof ApiError && caught.kind === "conflict" ? "Submission 状态或内容哈希已经变化，请返回队列后重新核对。" : "审批决定未能保存。";
  } finally {
    acting.value = null;
  }
}
watch(() => route.params.submissionId, load, { immediate: true });
onBeforeUnmount(() => { loadSequence++; });
</script>

<template>
  <div class="admin-page submission-review-page" data-submission-review>
    <RouterLink class="back-link" :to="{ name: 'admin-submissions' }">{{ t("← 返回提交审批") }}</RouterLink>
    <section v-if="state === 'loading'" class="page-state" aria-live="polite">{{ t("正在读取冻结 Submission…") }}</section>
    <section v-else-if="state === 'not-found'" class="page-state"><span class="state-symbol" aria-hidden="true">404</span><h1>{{ t("未找到待审批 Submission") }}</h1></section>
    <section v-else-if="state === 'error'" class="page-state" role="alert"><span class="state-symbol is-error" aria-hidden="true">!</span><h1>{{ t(error ?? "") }} <small v-if="errorRequestId">{{ t("请求编号：{requestId}", { requestId: errorRequestId }) }}</small></h1><button class="button-secondary" type="button" @click="load">{{ t("重新加载") }}</button></section>
    <FrozenSubmissionScope v-else-if="detail && snapshot" :key="detail.submission.id">
      <header class="page-heading">
        <div><p class="eyebrow">REVIEWER SUBMISSION · #{{ selectedVersion?.round_number ?? detail.submission.submission_number }}</p><h1>{{ detail.bibliography.title }}</h1><p>{{ detail.bibliography.journal }} · {{ detail.bibliography.publication_year }} · {{ detail.bibliography.volume }}({{ detail.bibliography.issue }})</p><a class="button-secondary source-pdf-link" data-source-pdf :href="sourcePdfUrl()" target="_blank" rel="noopener">{{ t("打开 Source PDF ↗") }}</a></div>
        <dl class="submission-identity"><div><dt>Paper</dt><dd><code>{{ detail.bibliography.paper_key }}</code></dd></div><div><dt>Content hash</dt><dd><code>{{ detail.submission.content_hash }}</code></dd></div><div><dt>{{ t("提交时间") }}</dt><dd>{{ formatDate(detail.submission.submitted_at) }}</dd></div></dl>
      </header>
      <section v-if="rounds" class="review-version-navigation panel" data-review-version-navigation :aria-label="t('Reviewer 提交版本')">
        <nav class="review-version-controls">
          <RouterLink v-if="previousVersion && !acting" class="button-secondary" data-previous-review-version :to="{ name: 'admin-submission-detail', params: { submissionId: previousVersion.id } }">{{ t('← 上一版') }}</RouterLink>
          <span v-else class="button-secondary is-disabled" aria-disabled="true">{{ t('← 上一版') }}</span>
          <label><span>{{ t('第 {number} / {total} 次提交', { number: selectedVersion?.round_number ?? '—', total: versions.length }) }}</span>
            <select :value="detail.submission.id" :disabled="!!acting" :aria-label="t('选择提交版本')" @change="chooseVersion">
              <option v-for="version in versions" :key="version.id" :value="version.id">{{ t('第 {number} 次提交', { number: version.round_number }) }} · {{ formatDate(version.submitted_at) }} · {{ reviewVersionStatus(version.status) }}</option>
            </select>
          </label>
          <RouterLink v-if="nextVersion && !acting" class="button-secondary" data-next-review-version :to="{ name: 'admin-submission-detail', params: { submissionId: nextVersion.id } }">{{ t('下一版 →') }}</RouterLink>
          <span v-else class="button-secondary is-disabled" aria-disabled="true">{{ t('下一版 →') }}</span>
        </nav>
        <div v-if="selectedVersion" class="review-version-meta"><strong>{{ selectedVersion.submitted_by_name }}</strong><time :datetime="selectedVersion.submitted_at">{{ formatDate(selectedVersion.submitted_at) }}</time><span class="status-chip">{{ reviewVersionStatus(selectedVersion.status) }}</span></div>
        <p v-if="selectedVersion?.status === 'awaiting_reviewer'">{{ t('本次提交后的补填尚未由 Reviewer 确认；保留原有修改与确认，只需核对新增或受影响内容后重新提交。') }}</p>
        <p v-if="rounds.supplements.some(s => s.phase === 'before_submission')">{{ t('人工修改以补填后的底稿为参照；上次提交的原始内容可切换版本查看。') }}</p>
        <div v-if="selectedVersion?.followup_decision" class="review-followup" data-followup-decision><strong>{{ t('后续退回／补填核对要求') }}</strong> · {{ formatDate(selectedVersion.followup_decision.decided_at) }}<p>{{ selectedVersion.followup_decision.reason }}</p></div>
        <p v-for="warning in rounds.warnings" :key="warning" class="message is-error">{{ warning }}</p>
      </section>
      <p v-if="detail.submission.reviewer_note" class="reviewer-attestation panel"><strong>{{ t("提交说明") }}</strong><span>{{ detail.submission.reviewer_note }}</span></p>
      <section v-if="detail.comparison?.reviewer_submission" class="original-reviewer-submission panel" data-original-reviewer-submission>
        <header><strong>{{ t("原 Reviewer 提交 · 第 {number} 次", { number: detail.comparison.reviewer_submission.submission_number }) }}</strong><span>{{ formatDate(detail.comparison.reviewer_submission.submitted_at) }}</span></header>
        <p>{{ t("保留本轮 Reviewer 修改及确认记录；后续补填内容仍需审批。") }}</p>
        <blockquote v-if="detail.comparison.reviewer_submission.reviewer_note">{{ detail.comparison.reviewer_submission.reviewer_note }}</blockquote>
        <RouterLink :to="{ name: 'admin-submission-detail', params: { submissionId: detail.comparison.reviewer_submission.id } }">{{ t("查看原 Reviewer 提交 →") }}</RouterLink>
      </section>
      <p v-if="error" class="message inline-feedback is-error" role="alert">{{ t(error ?? "") }} <small v-if="errorRequestId">{{ t("请求编号：{requestId}", { requestId: errorRequestId }) }}</small></p>
      <SubmissionComparison :snapshot="snapshot" :comparison="detail.comparison" :paper-id="detail.submission.paper_id" />
      <details v-for="supplement in rounds?.supplements ?? []" :key="supplement.phase" class="panel approval-supplements" data-ai-supplements @toggle="supplementOpen[supplement.phase] = ($event.target as HTMLDetailsElement).open">
        <summary>{{ t(supplement.phase === 'after_submission' ? '提交后补填 · 待 Reviewer 核对' : '本轮 AI 预填／补填 · 不计入 Reviewer 修改') }} <small>· {{ formatDate(supplement.submitted_at) }}</small></summary>
        <p>{{ t('补填单独展示；操作来源保留在历史中，不代表 Reviewer 已确认。') }}</p>
        <SubmissionComparison v-if="supplementOpen[supplement.phase]" :snapshot="supplement.snapshot" :comparison="supplement.comparison" :paper-id="detail.submission.paper_id" />
      </details>
      <details class="panel approval-full-content" data-full-submission @toggle="fullContentOpen = ($event.target as HTMLDetailsElement).open">
        <summary>{{ t("查看完整提交内容") }}</summary>
        <template v-if="fullContentOpen">
      <ArticleMetadata v-if="detail" :metadata="detail.bibliography" :source-context="{paperId:detail.submission.paper_id,pageCount:snapshot.source.page_count,sha256:snapshot.source.sha256}" />
      <AiProvenance :records="snapshot.ai_provenance ?? []" />
      <HighlightCards :items="snapshot.compound_highlights ?? []" :compounds="snapshot.compounds" :evidence="snapshot.evidence" :depiction="highlightDepiction" />
      <section class="submission-science panel" data-structure-comparison>
        <div class="section-heading"><div><p class="eyebrow">STRUCTURE VERIFICATION</p><h2>{{ t("结构原图与 RDKit 对照") }}</h2></div></div>
        <div class="submission-structure-grid">
          <article v-for="structure in snapshot.structures" :key="structure.id">
            <header><strong>{{ compoundLabels.get(structure.compound_id) ?? structure.compound_id }}</strong><ReviewHint :hint="snapshot.compounds.find(item => item.id === structure.compound_id)?.review_hint" /><span class="status-chip">{{ statusLabel(structure.status) }}</span></header>
            <div class="submission-image-pair">
              <FrozenEvidence v-for="image in sourceImagesByCompound.get(structure.compound_id) ?? []" :key="image.id" :evidence="image" :snapshot="snapshot" :paper-id="detail.submission.paper_id" :current-source-sha="snapshot.source.sha256" />
              <div><span>{{ t("RDKit 重绘") }}</span><img v-if="structure.depiction_asset_id" data-rdkit-depiction :src="adminAssetUrl(structure.depiction_asset_id)" :alt="t('RDKit 结构重绘')"><code v-else>{{ structure.canonical_smiles ?? structure.smiles ?? "—" }}</code></div>
            </div>
            <code>{{ structure.canonical_smiles ?? structure.smiles ?? "—" }}</code>
          </article>
        </div>
      </section>
      <section class="submission-science panel" data-submission-lineage>
        <div class="section-heading"><div><p class="eyebrow">LINEAGE</p><h2>{{ t("完整 Lineage") }}</h2></div></div>
        <article v-for="lineage in snapshot.lineages" :key="lineage.id" class="submission-lineage-card">
          <header><strong>{{ lineage.lineage_label }}</strong><span class="status-chip">{{ t(lineageTypeLabels[lineage.lineage_type]) }}</span><span>{{ lineage.description }}</span></header>
          <div class="lineage-member-roles">
            <span v-for="member in snapshot.lineage_members.filter((item) => item.lineage_id === lineage.id)" :key="member.id"><strong>{{ compoundLabels.get(member.compound_id) }}</strong><small>{{ statusLabel(member.role) }}</small></span>
          </div>
          <div v-for="edge in snapshot.lineage_edges.filter((item) => item.lineage_id === lineage.id)" :key="edge.id" class="submission-edge-row"><strong>{{ compoundLabels.get(edge.parent_compound_id) }} → {{ compoundLabels.get(edge.child_compound_id) }}</strong><ReviewHint :hint="edge.review_hint" /><span>{{ edge.relation_type }} · {{ edge.modification_summary ?? "—" }}</span></div>
        </article>
      </section>
      <section class="submission-science panel" data-submission-evidence>
        <div class="section-heading"><div><p class="eyebrow">EVIDENCE & ACTIVITY</p><h2>{{ t("关系证据与活性") }}</h2></div></div>
        <div class="submission-evidence-grid">
          <div>
            <article v-for="item in snapshot.evidence" :key="item.id" class="published-evidence-card">
              <header><strong>{{ statusLabel(item.kind) }} {{ t("· 第") }} {{ item.page_number }} {{ t("页") }}</strong><span>{{ item.caption }}</span></header>
              <blockquote v-if="item.quoted_text">{{ item.quoted_text }}</blockquote>
              <a data-evidence-pdf-locator :href="sourcePdfUrl(item.page_number)" target="_blank" rel="noopener">{{ t("在 Source PDF 第") }} {{ item.page_number }} {{ t("页核对 bbox ↗") }}</a>
              <small v-for="link in snapshot.edge_evidence_links.filter((row) => row.evidence_id === item.id)" :key="link.id">{{ statusLabel(link.role) }} · {{ edgeLabel(link.edge_id) }}</small>
            </article>
            <p v-if="!snapshot.evidence.length" class="section-empty">{{ t("没有报告 Evidence。") }}</p>
          </div>
          <div class="activity-table-wrap">
            <table v-if="snapshot.activities.length" class="data-table">
              <thead><tr><th>Compound</th><th>Assay</th><th>Metric</th><th>Value</th></tr></thead>
              <tbody><tr v-for="activity in snapshot.activities" :key="activity.id"><td>{{ compoundLabels.get(activity.compound_id) }}</td><td>{{ activity.assay_name }} <ReviewHint :hint="activity.review_hint" /></td><td>{{ activity.metric }}</td><td><strong>{{ activity.operator }} {{ activity.value }} {{ activity.unit ?? "" }}</strong></td></tr></tbody>
            </table>
            <p v-else class="section-empty">{{ t("没有报告 Activity。") }}</p>
          </div>
        </div>
      </section>
        </template>
      </details>
      <details class="panel approval-full-history" data-change-history @toggle="historyOpen = ($event.target as HTMLDetailsElement).open">
        <summary>{{ t("查看完整操作历史") }} · {{ detail.change_events.length }}</summary>
        <SubmissionDiff v-if="historyOpen" :events="detail.change_events" />
      </details>
      <section class="decision-panel panel">
        <div class="section-heading"><div><p class="eyebrow">ADMIN DECISION</p><h2>{{ t("审批决定") }}</h2></div></div>
        <div v-if="decision" class="submission-success" data-decision-success>
          <strong>{{ t(decision.decision.action === 'approve' ? '已批准并发布' : '已退回 Reviewer 修改') }}</strong><p>{{ decision.decision.reason }}</p>
          <RouterLink v-if="decision.published_version" class="button-secondary" data-published-paper-link :to="{ name: 'paper-detail', params: { paperId: decision.published_version.paper_id } }">{{ t("查看正式文章 →") }}</RouterLink>
        </div>
        <div v-else-if="!canDecide" class="historical-review" data-historical-review>
          <strong>{{ t('此版本只读，不能重复审批。') }}</strong>
          <template v-if="selectedVersion?.decision"><p>{{ reviewVersionStatus(selectedVersion.status) }} · {{ formatDate(selectedVersion.decision.decided_at) }}</p><p class="decision-reason">{{ selectedVersion.decision.reason }}</p></template>
          <p v-else-if="selectedVersion?.status === 'awaiting_reviewer'">{{ t('待 Reviewer 核对补填并重新提交后，再进行审批。') }}</p>
          <RouterLink v-if="nextVersion" class="button-secondary" :to="{ name: 'admin-submission-detail', params: { submissionId: versions[versions.length - 1]?.id } }">{{ t('查看最新提交 →') }}</RouterLink>
        </div>
        <template v-else>
          <label class="form-field"><span>{{ t("决定理由（必填）") }}</span><textarea v-model="reason" data-decision-reason rows="4" :placeholder="t('记录批准依据，或明确需要 Reviewer 修改的内容。')"></textarea></label>
          <div class="decision-actions"><button class="button-secondary" data-request-changes type="button" :disabled="decisionDisabled" @click="decide('request_changes')">{{ t("退回修改") }}</button><button class="button-primary" data-approve-submission type="button" :disabled="decisionDisabled" @click="decide('approve')">{{ t("批准并发布") }}</button></div>
        </template>
      </section>
    </FrozenSubmissionScope>
  </div>
</template>

<style scoped>
.original-reviewer-submission { margin: 1rem 0; padding: 1rem; }
.original-reviewer-submission header { display: flex; gap: .75rem; flex-wrap: wrap; }
.original-reviewer-submission blockquote { margin: .75rem 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.approval-full-content, .approval-full-history { margin: 1rem 0; }
.approval-full-content > summary, .approval-full-history > summary { cursor: pointer; font-weight: 600; padding: .5rem; }
.review-version-navigation { margin: 1rem 0; padding: 1rem; }
.review-version-controls, .review-version-meta { display: flex; align-items: center; gap: .75rem; flex-wrap: wrap; }
.review-version-controls label { display: grid; flex: 1; gap: .4rem; min-width: 0; }
.review-version-controls select { width: 100%; min-width: 0; max-width: 100%; padding: .5rem; }
.review-version-meta { margin-top: .75rem; }
.review-version-navigation p, .decision-reason { white-space: pre-wrap; overflow-wrap: anywhere; }
.is-disabled { opacity: .5; }
.approval-supplements { margin: 1rem 0; padding: 1rem; }
.approval-supplements > summary { cursor: pointer; font-weight: 600; }
.approval-supplements small { font-weight: 400; }
@media (max-width: 640px) { .review-version-controls label { order: -1; flex-basis: 100%; } }
</style>

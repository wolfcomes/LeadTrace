<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import type { Changeset, RevisionDiff } from "../api/schema";
import { ApiError } from "../api/client";
import ChangesetDiff from "../review/changesets/ChangesetDiff.vue";
import { fetchChangesetDiff, fetchChangesets } from "../review/api";
import ScientificApprovalReview from "./ScientificApprovalReview.vue";
import {
  decideApproval,
  fetchApprovals,
  fetchScientificEvidence,
  type ApprovalAction,
  type ApprovalDecision,
  type ScientificEvidence,
} from "./api";

type LoadStatus = "idle" | "loading" | "ready" | "error";

const changesets = ref<Changeset[]>([]);
const decisions = ref<ApprovalDecision[]>([]);
const diffs = ref<RevisionDiff[]>([]);
const evidence = ref<ScientificEvidence | null>(null);
const selectedId = ref("");
const loadedReviewKey = ref("");
const diffStatus = ref<LoadStatus>("idle");
const evidenceStatus = ref<LoadStatus>("idle");
const reason = ref("");
const loading = ref(true);
const acting = ref<ApprovalAction | null>(null);
const error = ref<string | null>(null);
const notice = ref<string | null>(null);

const pending = computed(() => changesets.value.filter((entry) => entry.workflow_state === "submitted"));
const selected = computed(() => changesets.value.find((entry) => entry.id === selectedId.value) ?? null);
const selectedDecisions = computed(() => decisions.value.filter((entry) => entry.changeset_id === selectedId.value));
function reviewKey(changeset: Changeset): string {
  return `${changeset.id}:${changeset.version}:${changeset.submitted_content_hash ?? ""}`;
}
const selectedReviewKey = computed(() => selected.value ? reviewKey(selected.value) : "");
const reviewReady = computed(() => (
  selected.value !== null
  && selected.value.workflow_state === "submitted"
  && selected.value.submitted_content_hash !== null
  && loadedReviewKey.value === selectedReviewKey.value
  && diffStatus.value === "ready"
  && evidenceStatus.value === "ready"
  && evidence.value?.changeset_id === selected.value.id
  && evidence.value.submission_version === selected.value.version
  && evidence.value.snapshot_hash === selected.value.submitted_content_hash
));
const decisionDisabled = computed(() => (
  loading.value || !reviewReady.value || !reason.value.trim() || acting.value !== null
));

let reviewRequestGeneration = 0;

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    const [allChangesets, allDecisions] = await Promise.all([
      fetchChangesets(),
      fetchApprovals(),
    ]);
    changesets.value = allChangesets;
    decisions.value = allDecisions;
    if (!selectedId.value || !allChangesets.some((entry) => entry.id === selectedId.value)) {
      selectedId.value = allChangesets.find((entry) => entry.workflow_state === "submitted")?.id ?? "";
    }
  } catch (caught) {
    error.value = caught instanceof ApiError
      ? `审批数据未能读取。请求编号：${caught.requestId ?? "未知"}`
      : "审批数据未能读取。";
  } finally {
    loading.value = false;
  }
}

async function loadReviewData(changeset: Changeset | null): Promise<void> {
  const generation = ++reviewRequestGeneration;
  const changesetId = changeset?.id ?? "";
  const requestKey = changeset ? reviewKey(changeset) : "";
  loadedReviewKey.value = requestKey;
  diffs.value = [];
  evidence.value = null;
  diffStatus.value = changesetId ? "loading" : "idle";
  evidenceStatus.value = changesetId ? "loading" : "idle";
  if (!changeset) return;

  const isCurrent = () => (
    generation === reviewRequestGeneration
    && selectedReviewKey.value === requestKey
  );
  const diffRequest = (async () => {
    try {
      const result = await fetchChangesetDiff(changesetId);
      if (!isCurrent()) return;
      diffs.value = result;
      diffStatus.value = "ready";
    } catch {
      if (!isCurrent()) return;
      diffs.value = [];
      diffStatus.value = "error";
    }
  })();
  const evidenceRequest = (async () => {
    try {
      const result = await fetchScientificEvidence(changesetId);
      if (!isCurrent()) return;
      if (
        result.changeset_id !== changesetId
        || result.submission_version !== changeset.version
        || result.snapshot_hash !== changeset.submitted_content_hash
      ) {
        evidence.value = null;
        evidenceStatus.value = "error";
        return;
      }
      evidence.value = result;
      evidenceStatus.value = "ready";
    } catch {
      if (!isCurrent()) return;
      evidence.value = null;
      evidenceStatus.value = "error";
    }
  })();
  await Promise.all([diffRequest, evidenceRequest]);
  if (!isCurrent()) {
    return;
  }
}

async function decide(action: ApprovalAction): Promise<void> {
  if (!selected.value || !reason.value.trim() || !reviewReady.value) return;
  acting.value = action;
  error.value = null;
  notice.value = null;
  try {
    const result = await decideApproval(
      selected.value.id,
      action,
      selected.value.version,
      reason.value.trim(),
    );
    notice.value = action === "approve"
      ? "已批准，待发布；请在发布管理中创建并发布 successor Release。"
      : result.idempotent ? "该决定已经记录。" : "审批决定已记录。";
    reason.value = "";
    await load();
  } catch (caught) {
    error.value = caught instanceof ApiError && caught.kind === "conflict"
      ? "修改集已经发生变化，请刷新后重新核对。"
      : "审批决定未能保存。";
  } finally {
    acting.value = null;
  }
}

watch(selectedReviewKey, () => { void loadReviewData(selected.value); });
onMounted(load);
</script>

<template>
  <div class="approval-page admin-page review-workspace">
    <header class="page-heading">
      <div>
        <p class="eyebrow">CONTROLLED REVIEW</p>
        <h1>审批中心</h1>
        <p>逐项核对提交快照、科学字段差异、证据定位和历史决定。</p>
      </div>
      <span class="queue-count status-chip is-pending">{{ pending.length }} 项待审批</span>
    </header>

    <p v-if="error" class="message inline-feedback is-error" role="alert">{{ error }}</p>
    <p v-if="notice" class="message inline-feedback is-success" data-approval-notice role="status">{{ notice }}</p>

    <div class="approval-layout">
      <aside class="queue panel" aria-label="待审批修改集">
        <div class="queue-heading">
          <h2>审批队列</h2>
          <button class="button-quiet" type="button" title="刷新审批队列" :disabled="loading" @click="load">刷新</button>
        </div>
        <button
          v-for="entry in pending"
          :key="entry.id"
          type="button"
          :class="['queue-item', { active: entry.id === selectedId }]"
          @click="selectedId = entry.id"
        >
          <strong>{{ entry.title }}</strong>
          <span>{{ entry.reason }}</span>
          <code>{{ entry.id }}</code>
        </button>
        <p v-if="!loading && pending.length === 0" class="empty">当前没有待审批修改集。</p>
      </aside>

      <main class="approval-workspace panel">
        <section class="summary-band panel">
          <div>
            <p class="eyebrow">SUBMITTED SNAPSHOT</p>
            <h2>{{ selected?.title ?? "选择待审批修改集" }}</h2>
            <p>{{ selected?.reason ?? "从左侧审批队列选择一项后查看详细差异。" }}</p>
            <RouterLink
              v-if="selected"
              class="button-secondary workspace-link"
              :to="`/review/changesets/${selected.id}`"
              data-review-workspace-link
            >打开完整核查工作台</RouterLink>
          </div>
          <dl v-if="selected">
            <div><dt>文献</dt><dd><code>{{ selected.paper_id }}</code></dd></div>
            <div><dt>版本</dt><dd>v{{ selected.version }}</dd></div>
            <div><dt>状态</dt><dd>{{ selected.workflow_state }}</dd></div>
          </dl>
        </section>

        <p v-if="selected && diffStatus === 'loading'" class="review-load-status inline-feedback" data-diff-status role="status">正在读取结构化变更…</p>
        <p v-else-if="selected && diffStatus === 'error'" class="review-load-status inline-feedback is-error" data-diff-status role="alert">结构化变更未能读取，审批操作已禁用。</p>
        <ChangesetDiff v-else-if="selected && diffStatus === 'ready'" :diffs="diffs" />

        <ScientificApprovalReview
          v-if="selected"
          :changeset="selected"
          :diffs="diffs"
          :evidence="evidence"
          :evidence-status="evidenceStatus"
        />

        <section class="decision-panel panel" aria-labelledby="decision-title">
          <div>
            <p class="eyebrow">ADMIN DECISION</p>
            <h2 id="decision-title">审批决定</h2>
          </div>
          <label for="decision-reason">决定理由</label>
          <textarea
            id="decision-reason"
            class="form-control"
            v-model="reason"
            rows="4"
            placeholder="记录批准依据或需要修改、拒绝的具体原因"
          ></textarea>
          <div class="decision-actions">
            <button type="button" class="button-secondary" :disabled="decisionDisabled" @click="decide('request-changes')">请求修改</button>
            <button type="button" class="button-danger" :disabled="decisionDisabled" @click="decide('reject')">拒绝</button>
            <button type="button" class="button-primary" :disabled="decisionDisabled" @click="decide('approve')">批准</button>
          </div>
        </section>

        <section class="history-panel panel table-wrap">
          <h2>审批历史</h2>
          <table class="data-table">
            <thead><tr><th>决定</th><th>理由</th><th>提交版本</th><th>时间</th></tr></thead>
            <tbody>
              <tr v-for="entry in selectedDecisions" :key="entry.id">
                <td>{{ entry.decision }}</td><td>{{ entry.reason }}</td><td>v{{ entry.submission_version }}</td><td>{{ entry.created_at }}</td>
              </tr>
              <tr v-if="selectedDecisions.length === 0"><td colspan="4" class="empty">暂无审批记录</td></tr>
            </tbody>
          </table>
        </section>
      </main>
    </div>
  </div>
</template>

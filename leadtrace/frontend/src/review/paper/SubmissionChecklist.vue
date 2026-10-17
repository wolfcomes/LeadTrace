<script setup lang="ts">
import { usePendingEdit } from "./usePendingEdits";
import { problemText, submitProblem } from "./problemSubmission";
import { useReviewProgress } from "./useReviewProgress";
import { t } from "../../i18n";
import { computed, onMounted, ref, watch } from "vue";

import { ApiError } from "../../api/client";
import { useAuthStore } from "../../auth/store";
import { getSubmissionValidation, submitWorkspace } from "../../v2/api";
import type { PaperWorkspace, SubmissionBlocker } from "../../v2/types";

const props = defineProps<{ workspace: PaperWorkspace; readOnly?: boolean }>();
const emit = defineEmits<{
  navigate: [tab: "bibliography" | "compounds" | "lineages" | "evidence", entityId?: string];
  mutated: [workspaceVersion: number];
  conflict: [];
}>();
const auth = useAuthStore();
const progress = useReviewProgress();
const blockers = ref<SubmissionBlocker[]>([]);
const valid = ref(false);
const loading = ref(true);
const saving = ref(false);
const confirmed = ref(false);
const reviewerNote = ref("");
const error = ref("");
const submitted = ref(false);
const problemReason = ref("");
const submittedProblem = ref(false);
let problemAttempt: {identity: string; key: string} | null = null;
const canSubmitProblem = computed(() => Boolean(problemReason.value.trim()) && !props.readOnly && !saving.value && !submitted.value);

async function reportProblem(): Promise<void> {
  if (!canSubmitProblem.value) return;
  saving.value = true;
  error.value = "";
  try {
    const identity = JSON.stringify([props.workspace.id, props.workspace.version, problemReason.value.trim()]);
    if (problemAttempt?.identity !== identity) problemAttempt = {identity, key: 'problem-' + crypto.randomUUID()};
    const result = await submitProblem(props.workspace.id, props.workspace.version, problemReason.value.trim(), auth.csrfToken, problemAttempt.key);
    submittedProblem.value = true;
    submitted.value = true;
    emit("mutated", result.workspace_version);
  } catch (reason) {
    if (reason instanceof ApiError && reason.code === "WORKSPACE_VERSION_CONFLICT") {
      emit("conflict");
      error.value = "Workspace 已更新，正在重新载入后重新检查。";
    } else {
      error.value = "提交未完成，请重试。";
    }
  } finally { saving.value = false; }
}

const canSubmit = computed(() => valid.value
  && confirmed.value
  && !props.readOnly
  && !saving.value
  && !submitted.value);

watch(() => props.workspace.id, () => { void loadValidation(); });
watch(() => props.workspace.version, (version, previous) => {
  if (version !== previous && !submitted.value) {
    confirmed.value = false;
    void loadValidation();
  }
});

function targetTab(blocker: SubmissionBlocker): "bibliography" | "compounds" | "lineages" | "evidence" {
  if (blocker.section_key === "bibliography") return "bibliography";
  if (blocker.section_key === "compounds" || blocker.section_key === "structures") return "compounds";
  if (blocker.section_key === "activities" || blocker.entity_type === "activity") return "compounds";
  if (blocker.section_key === "lineages") return "lineages";
  if (blocker.entity_type === "lineage_edge") return "lineages";
  return "evidence";
}

function openBlocker(blocker: SubmissionBlocker): void {
  emit("navigate", targetTab(blocker), blocker.entity_id ?? undefined);
}

async function loadValidation(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const result = await getSubmissionValidation(props.workspace.id);
    valid.value = result.valid;
    blockers.value = result.blockers;
  } catch {
    valid.value = false;
    blockers.value = [];
    error.value = "提交检查暂时无法完成，请重新检查。";
  } finally {
    loading.value = false;
  }
}

async function submit(): Promise<void> {
  if (!canSubmit.value) return;
  saving.value = true;
  error.value = "";
  try {
    const result = await submitWorkspace(props.workspace.id, {
      expected_workspace_version: props.workspace.version,
      reviewer_note: reviewerNote.value.trim() || null,
    }, `submit-${props.workspace.id}-v${props.workspace.version}`, auth.csrfToken);
    submitted.value = true;
    emit("mutated", result.workspace_version);
  } catch (reason) {
    if (reason instanceof ApiError && reason.code === "WORKSPACE_VERSION_CONFLICT") {
      emit("conflict");
      error.value = "Workspace 已更新，正在重新载入后重新检查。";
    } else if (reason instanceof ApiError && reason.code === "SUBMISSION_BLOCKED") {
      error.value = "Workspace 内容在提交时未通过校验，请处理以下项目。";
      await loadValidation();
    } else {
      error.value = "提交未完成，请重试。";
    }
  } finally {
    saving.value = false;
  }
}

watch(() => progress?.progress.value, () => { if (!loading.value) { confirmed.value = false; void loadValidation(); } });
onMounted(loadValidation);
usePendingEdit(() => saving.value || reviewerNote.value.trim() || problemReason.value.trim() || confirmed.value);
</script>

<template>
  <section class="submission-checklist">
    <header class="section-heading"><div><p class="eyebrow">REVIEW & SUBMIT</p><h2>{{ t("检查与提交") }}</h2></div><button class="button-secondary" type="button" :disabled="loading || saving" @click="loadValidation">{{ t("重新检查") }}</button></header>
    <section v-if="progress?.progress.value" class="review-progress-summary">
      <h3>{{ t('条目查看进度') }}</h3><p>{{ t('只在 Compound 和 Lineage 两层记录已查看；组内内容变化后需重新查看，科学审核仍需人工确认。') }}</p>
      <div class="review-progress-sections"><span v-for="section in progress.progress.value.sections" :key="section.section_key" class="view-state" :class="{'is-viewed':section.complete}">{{ t(section.section_key) }} {{ section.viewed }} / {{ section.total }}</span></div>
      <details v-if="progress.unread.value.length"><summary>{{ t('未查看条目') }} ({{ progress.unread.value.length }})</summary><button v-for="item in progress.unread.value" :key="item.kind + item.entity_id" type="button" class="button-secondary" @click="emit('navigate', item.kind === 'compound' ? 'compounds' : 'lineages',item.entity_id)">{{ item.kind }} · {{ item.label }}</button></details>
    </section>
    <p v-if="error" class="inline-feedback is-error" role="alert">{{ t(error) }}</p>
    <p v-if="loading" class="workspace-empty-copy">{{ t("正在执行服务端完整性检查…") }}</p>
    <template v-else-if="submitted">
      <div class="submission-success" role="status"><strong>{{ submittedProblem ? problemText("文章问题已提交", "Article problem submitted") : t("已提交给 Admin 审批") }}</strong><p>{{ t("本次内容已冻结为不可变 Submission；Admin 批准前不会进入正式文章页面。") }}</p></div>
    </template>
    <template v-else>
      <section class="validation-summary" :data-valid="valid ? 'true' : 'false'">
        <div><strong>{{ valid ? t("提交检查已通过") : t("{p0} 个项目仍需处理", { p0: blockers.length }) }}</strong><p>{{ valid ? t("六个固定区段及其科学记录满足提交规则。") : t("点击项目可直接打开对应标签页和记录。") }}</p></div>
        <span class="status-chip">{{ valid ? "READY" : "BLOCKED" }}</span>
      </section>
      <div v-if="blockers.length" class="submission-blocker-list">
        <button v-for="blocker in blockers" :key="`${blocker.code}:${blocker.entity_id || blocker.section_key}`" data-submission-blocker type="button" @click="openBlocker(blocker)">
          <span><strong>{{ blocker.message }}</strong><small>{{ blocker.section_key || "workspace" }} · {{ blocker.entity_type }}</small></span><span aria-hidden="true">{{ t("打开 →") }}</span>
        </button>
      </div>
      <form class="submission-confirmation" @submit.prevent="submit">
        <label class="form-field">Reviewer note<textarea v-model="reviewerNote" data-reviewer-note rows="4" maxlength="10000" :disabled="readOnly || saving" :placeholder='t("可选：给 Admin 的整体说明")'></textarea></label>
        <label class="reviewer-confirmation"><input v-model="confirmed" data-reviewer-confirmation type="checkbox" :disabled="readOnly || saving || !valid"><span>{{ t("我已核对整篇文章、Source PDF、结构、Lineage、Edge Evidence 与 Activity；当前记录可以提交给 Admin 审批。") }}</span></label>
        <p v-if="readOnly" class="inline-feedback is-warning">{{ t("当前 Workspace 为只读状态，不能再次提交。") }}</p>
        <button class="button-primary" data-submit-paper type="button" :disabled="!canSubmit" @click="submit">{{ saving ? t("正在冻结 Submission…") : t("提交给 Admin 审批") }}</button>
      </form>
      <section class="submission-confirmation" data-problem-submission>
        <h3>{{ problemText('反馈文章问题并提交', 'Report an article problem and submit') }}</h3>
        <p>{{ problemText('文章存在重大问题时，可提交当前内容和未完成清单。无需全部确认；问题反馈不能直接批准发布，Admin 可退回处理。', 'For major article problems, freeze the current content and incomplete checklist without confirming every item. Problem reports cannot be published; an Admin can return them for follow-up.') }}</p>
        <label class="form-field">{{ problemText('问题说明（必填）', 'Problem explanation (required)') }}<textarea v-model="problemReason" data-problem-reason rows="4" maxlength="10000" :disabled="readOnly || saving" /></label>
        <button class="button-secondary" data-submit-problem type="button" :disabled="!canSubmitProblem" @click="reportProblem">{{ saving ? t('正在冻结 Submission…') : problemText('反馈文章问题并提交', 'Report an article problem and submit') }}</button>
      </section>
    </template>
  </section>
</template>

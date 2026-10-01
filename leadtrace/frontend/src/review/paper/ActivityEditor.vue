<script setup lang="ts">
import FieldExample from "./FieldExample.vue";
import { t } from "../../i18n";
import ReviewHint from "./ReviewHint.vue";
import { computed, nextTick, onMounted, ref, watch } from "vue";

import EvidenceExcerpt from "./EvidenceExcerpt.vue";
import EvidenceEditor from "./EvidenceEditor.vue";

import { ApiError } from "../../api/client";
import { useAuthStore } from "../../auth/store";
import { createActivity, deleteActivity, listActivities, listCompounds, listEvidence, updateActivity } from "../../v2/api";
import type { Activity, Compound, Evidence, PaperWorkspace } from "../../v2/types";

const props = defineProps<{ workspace: PaperWorkspace; compound?: Compound; selectedEntityId?: string; active?: boolean; readOnly?: boolean }>();
const emit = defineEmits<{ select: [entityId: string]; mutated: [workspaceVersion: number]; conflict: [] }>();
const auth = useAuthStore();
const manageEvidence = ref(false);
const compounds = ref<Compound[]>([]);
const evidenceItems = ref<Evidence[]>([]);
const evidenceVersion = ref(props.workspace.version);
const activities = ref<Activity[]>([]);
const localVersion = ref(props.workspace.version);
let initialized = false;
const activityVersion = ref(props.workspace.version);
const loading = ref(true);
const busy = ref(false);
const showCreate = ref(false);
const compoundId = ref("");
const evidenceId = ref("");
const assayName = ref("");
const metric = ref("IC50");
const operator = ref<Activity["operator"]>("=");
const value = ref("");
const unit = ref("");
const context = ref("");
const editingActivityId = ref<string>();
const editEvidenceId = ref("");
const editAssayName = ref("");
const editMetric = ref("");
const editOperator = ref<Activity["operator"]>("=");
const editValue = ref("");
const editUnit = ref("");
const editContext = ref("");
const reviewHint = ref("");
const editReviewHint = ref("");
const error = ref("");
const editor = ref<HTMLElement | null>(null);
const filterCompoundId = ref("");
const page = ref(1);
const pageSize = 25;
const filteredActivities = computed(() => activities.value.filter((activity) => (
  !filterCompoundId.value || activity.compound_id === filterCompoundId.value
)));
const pageCount = computed(() => Math.max(1, Math.ceil(filteredActivities.value.length / pageSize)));
const visibleActivities = computed(() => filteredActivities.value.slice((page.value - 1) * pageSize, page.value * pageSize));

const evidenceById = computed(() => new Map(evidenceItems.value.map(item => [item.id, item])));
const activityEvidenceIds = computed(() => activities.value.flatMap(item => item.evidence_id ? [item.evidence_id] : []));

async function evidenceMutation(version:number): Promise<void> {
  evidenceItems.value = [];
  emit('mutated',version);
  try { const result=await listEvidence(props.workspace.id); evidenceItems.value=result.items; evidenceVersion.value=result.workspace_version; }
  catch { error.value='Evidence 暂时无法读取。'; }
}
const compoundById = computed(() => new Map(compounds.value.map((compound) => [compound.id, compound])));

watch(() => props.workspace.version, (version) => {
  if (version > localVersion.value) localVersion.value = version;
  if (initialized && props.active !== false && version !== activityVersion.value) void load();
});
watch(() => props.active,active => { if (active && activityVersion.value !== props.workspace.version) void load(); });
watch([() => props.workspace.id, () => props.compound?.id], () => {
  filterCompoundId.value = "";
  page.value = 1;
  cancelActivityEdit();
  resetForm();
  manageEvidence.value = false;
  void load();
});
watch(filterCompoundId, () => { page.value = 1; }, { flush: "sync" });
watch(pageCount, (count) => { page.value = Math.min(page.value, count); }, { flush: "sync" });
watch(() => props.selectedEntityId, (id) => { void revealActivity(id); });

async function revealActivity(id?: string): Promise<void> {
  const activity = activities.value.find((item) => item.id === id || item.evidence_id === id);
  if (!activity) return;
  if (filterCompoundId.value && filterCompoundId.value !== activity.compound_id) filterCompoundId.value = "";
  page.value = Math.floor(filteredActivities.value.findIndex((item) => item.id === activity.id) / pageSize) + 1;
  await nextTick();
  const row = Array.from(editor.value?.querySelectorAll<HTMLElement>("[data-activity-row]") ?? [])
    .find((item) => item.dataset.activityId === id);
  row?.scrollIntoView?.({ block: "center" });
}

function mutationError(reason: unknown, fallback: string): void {
  if (reason instanceof ApiError && reason.code === "WORKSPACE_VERSION_CONFLICT") {
    emit("conflict");
    error.value = "Workspace 已更新，正在重新载入全部 Activity 数据。";
    return;
  }
  error.value = fallback;
}

let loadEpoch = 0;
async function load(): Promise<void> {
  const epoch = ++loadEpoch;
  const scopedCompound = props.compound;
  activities.value = [];
  evidenceItems.value = [];
  loading.value = true;
  error.value = "";
  try {
    const [compoundResult, evidenceResult] = await Promise.all([
      scopedCompound ? Promise.resolve({ items: [scopedCompound], workspace_version: props.workspace.version }) : listCompounds(props.workspace.id),
      listEvidence(props.workspace.id),
    ]);
    if (epoch !== loadEpoch) return;
    compounds.value = compoundResult.items;
    evidenceItems.value = evidenceResult.items;
    evidenceVersion.value = evidenceResult.workspace_version;
    compoundId.value = compounds.value[0]?.id ?? "";
    const activityResults = await Promise.all(compounds.value.map((compound) => listActivities(compound.id)));
    if (epoch !== loadEpoch) return;
    activities.value = activityResults.flatMap((result) => result.items);
    initialized = true;
    activityVersion.value = Math.min(evidenceResult.workspace_version,...activityResults.map(x => x.workspace_version));
    localVersion.value = Math.max(
      compoundResult.workspace_version,
      evidenceResult.workspace_version,
      ...activityResults.map((result) => result.workspace_version),
    );
  } catch {
    if (epoch === loadEpoch) error.value = "Activity 数据暂时无法读取。";
  } finally {
    if (epoch === loadEpoch) loading.value = false;
  }
  if (epoch === loadEpoch) await revealActivity(props.selectedEntityId);
}

function resetForm(): void {
  evidenceId.value = "";
  assayName.value = "";
  metric.value = "IC50";
  operator.value = "=";
  value.value = "";
  unit.value = "";
  context.value = "";
  reviewHint.value = "";
  showCreate.value = false;
}

function startActivityEdit(activity: Activity): void {
  editingActivityId.value = activity.id;
  editEvidenceId.value = activity.evidence_id ?? "";
  editAssayName.value = activity.assay_name;
  editMetric.value = activity.metric;
  editOperator.value = activity.operator;
  editValue.value = String(activity.value);
  editUnit.value = activity.unit ?? "";
  editContext.value = activity.context ?? "";
  editReviewHint.value = activity.review_hint ?? "";
}

function cancelActivityEdit(): void {
  editingActivityId.value = undefined;
}

async function save(): Promise<void> {
  if (!compoundId.value || !assayName.value.trim() || !metric.value.trim() || !value.value.trim() || props.readOnly || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await createActivity(compoundId.value, {
      expected_workspace_version: localVersion.value,
      evidence_id: evidenceId.value || null,
      assay_name: assayName.value.trim(),
      metric: metric.value.trim(),
      operator: operator.value,
      value: value.value.trim(),
      unit: unit.value.trim() || null,
      context: context.value.trim() || null,
      review_hint: reviewHint.value.trim() || null,
    }, auth.csrfToken);
    activities.value = [...activities.value, result.activity];
    localVersion.value = result.workspace_version; activityVersion.value = result.workspace_version;
    resetForm();
    await revealActivity(result.activity.id);
    emit("select", result.activity.id);
    emit("mutated", result.workspace_version);
  } catch (reason) {
    mutationError(reason, "Activity 未能保存；请检查数值和必填字段。");
  } finally {
    busy.value = false;
  }
}

async function remove(activity: Activity): Promise<void> {
  if (props.readOnly || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await deleteActivity(activity.id, localVersion.value, auth.csrfToken);
    activities.value = activities.value.filter((item) => item.id !== activity.id);
    localVersion.value = result.workspace_version; activityVersion.value = result.workspace_version;
    emit("mutated", result.workspace_version);
  } catch (reason) {
    mutationError(reason, "Activity 未能删除，请重试。");
  } finally {
    busy.value = false;
  }
}

async function saveActivityEdit(): Promise<void> {
  const activityId = editingActivityId.value;
  if (!activityId || !editAssayName.value.trim() || !editMetric.value.trim() || !editValue.value.trim() || props.readOnly || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await updateActivity(activityId, {
      expected_workspace_version: localVersion.value,
      evidence_id: editEvidenceId.value || null,
      assay_name: editAssayName.value.trim(),
      metric: editMetric.value.trim(),
      operator: editOperator.value,
      value: editValue.value.trim(),
      unit: editUnit.value.trim() || null,
      context: editContext.value.trim() || null,
      review_hint: editReviewHint.value.trim() || null,
    }, auth.csrfToken);
    activities.value = activities.value.map((item) => item.id === activityId ? result.activity : item);
    localVersion.value = result.workspace_version; activityVersion.value = result.workspace_version;
    cancelActivityEdit();
    emit("select", activityId);
    emit("mutated", result.workspace_version);
  } catch (reason) {
    mutationError(reason, "Activity 修改未能保存；请检查数值和必填字段。");
  } finally {
    busy.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section id="workspace-activities" ref="editor" class="activity-editor" tabindex="-1">
    <header class="section-heading"><div><p class="eyebrow">ACTIVITIES</p><h2>{{ t("活性数据") }}</h2></div><button class="button-secondary" data-add-activity type="button" :disabled="readOnly || busy || compounds.length === 0" @click="showCreate = !showCreate">{{ t("添加 Activity") }}</button></header>
    <FieldExample :section="5" />
    <form v-if="showCreate" class="activity-create-form inline-create-form" @submit.prevent="save">
      <label v-if="!compound" class="form-field">Compound<select v-model="compoundId" :disabled="readOnly || busy"><option v-for="compound in compounds" :key="compound.id" :value="compound.id">{{ compound.compound_label }}</option></select></label>
      <label class="form-field">Assay<input v-model="assayName" placeholder="human MAO-B inhibition" required maxlength="512" :disabled="readOnly || busy"></label>
      <label class="form-field">Metric<input v-model="metric" placeholder="IC50" required maxlength="128" :disabled="readOnly || busy"></label>
      <label class="form-field">Operator<select v-model="operator" :disabled="readOnly || busy"><option value="=">=</option><option value="<">&lt;</option><option value="<=">≤</option><option value=">">&gt;</option><option value=">=">≥</option><option value="~">~</option></select></label>
      <label class="form-field">Value<input v-model="value" placeholder="10" required inputmode="decimal" :disabled="readOnly || busy"></label>
      <label class="form-field">Unit<input v-model="unit" placeholder="nM" maxlength="128" :disabled="readOnly || busy"></label>
      <label class="form-field">Evidence<select v-model="evidenceId" :disabled="readOnly || busy"><option value="">{{ t("无") }}</option><option v-for="item in evidenceItems" :key="item.id" :value="item.id">p{{ item.page_number }} · {{ item.quoted_text || item.caption || item.kind }}</option></select></label>
      <label class="form-field">Context<input v-model="context" maxlength="10000" :disabled="readOnly || busy"></label>
      <label class="form-field">{{ t("核对提示（可选，解决后清空）") }}<input v-model="reviewHint" data-create-activity-review-hint maxlength="1000" :disabled="readOnly || busy"></label>
      <button class="button-primary" type="button" :disabled="busy || !compoundId || !assayName.trim() || !metric.trim() || !value.trim()" @click="save">{{ t("保存 Activity") }}</button>
    </form>
    <form v-if="editingActivityId" class="activity-edit-form inline-create-form" @submit.prevent="saveActivityEdit">
      <label class="form-field">Assay<input v-model="editAssayName" required maxlength="512" :disabled="busy"></label>
      <label class="form-field">Metric<input v-model="editMetric" required maxlength="128" :disabled="busy"></label>
      <label class="form-field">Operator<select v-model="editOperator" :disabled="busy"><option value="=">=</option><option value="<">&lt;</option><option value="<=">≤</option><option value=">">&gt;</option><option value=">=">≥</option><option value="~">~</option></select></label>
      <label class="form-field">Value<input v-model="editValue" data-edit-activity-value required inputmode="decimal" :disabled="busy"></label>
      <label class="form-field">Unit<input v-model="editUnit" maxlength="128" :disabled="busy"></label>
      <label class="form-field">Evidence<select v-model="editEvidenceId" :disabled="busy"><option value="">{{ t("无") }}</option><option v-for="item in evidenceItems" :key="item.id" :value="item.id">p{{ item.page_number }} · {{ item.quoted_text || item.caption || item.kind }}</option></select></label>
      <label class="form-field">Context<input v-model="editContext" maxlength="10000" :disabled="busy"></label>
      <label class="form-field">{{ t("核对提示（可选，解决后清空）") }}<input v-model="editReviewHint" data-edit-activity-review-hint maxlength="1000" :disabled="readOnly || busy"></label>
      <div class="editor-actions"><button class="button-primary" data-save-activity-edit type="button" :disabled="busy || !editAssayName.trim() || !editMetric.trim() || !editValue.trim()" @click="saveActivityEdit">{{ t("保存修改") }}</button><button class="button-quiet" type="button" :disabled="busy" @click="cancelActivityEdit">{{ t("取消") }}</button></div>
    </form>
    <p v-if="error" class="inline-feedback is-error" role="alert">{{ t(error) }}</p>
    <p v-if="loading" class="workspace-empty-copy">{{ t("正在读取 Activity…") }}</p>
    <p v-else-if="!error && activities.length === 0" class="workspace-empty-copy">{{ compound ? t("当前化合物尚无活性记录。") : t("当前尚无 Activity。") }}{{ t("尚无记录不代表原文未报告，需核对原文后确认。") }}</p>
    <template v-else-if="!error">
    <div class="activity-list-controls">
      <label v-if="!compound" class="form-field">{{ t("按化合物筛选") }}<select v-model="filterCompoundId" data-activity-filter :disabled="busy"><option value="">{{ t("全部化合物") }}</option><option v-for="compound in compounds" :key="compound.id" :value="compound.id">{{ compound.compound_label }}</option></select></label>
      <p data-activity-count aria-live="polite">{{ t("共 {total} 条 · 筛选后 {filtered} 条 · 每页 {size} 条", { total: activities.length, filtered: filteredActivities.length, size: pageSize }) }}</p>
      <nav class="pagination" :aria-label='t("Activity 分页")'>
        <button class="button-quiet" data-activity-previous type="button" :disabled="busy || page <= 1" @click="page -= 1">{{ t("上一页") }}</button>
        <span data-activity-page aria-live="polite">{{ page }} / {{ pageCount }}</span>
        <button class="button-quiet" data-activity-next type="button" :disabled="busy || page >= pageCount" @click="page += 1">{{ t("下一页") }}</button>
      </nav>
    </div>
    <p v-if="filteredActivities.length === 0" class="workspace-empty-copy">{{ t("该化合物暂无 Activity；可选择其他化合物或全部化合物。") }}</p>
    <div v-else class="activity-table" role="table" :aria-label='t("Activity 条目")'>
      <article v-for="activity in visibleActivities" :key="activity.id" data-activity-row :data-activity-id="activity.id" :class="{ selected: activity.id === selectedEntityId }" role="row" @click="emit('select', activity.id)" tabindex="0" @keydown.enter="emit('select', activity.id)">
        <strong>{{ compoundById.get(activity.compound_id)?.compound_label || "?" }}</strong><span>{{ activity.assay_name }} <ReviewHint :hint="activity.review_hint" /></span><span>{{ activity.metric }}</span><code>{{ activity.operator }} {{ activity.value }} {{ activity.unit || "" }}</code><small>{{ activity.context || "—" }}</small><div v-if="!readOnly" class="editor-actions"><button class="button-quiet" data-edit-activity type="button" :disabled="busy" @click.stop="startActivityEdit(activity)">{{ t("编辑") }}</button><button class="button-quiet" type="button" :disabled="busy" @click.stop="remove(activity)">{{ t("删除") }}</button></div>
        <div class="activity-evidence" @click.stop>
          <EvidenceExcerpt v-if="activity.evidence_id && evidenceById.get(activity.evidence_id)" :evidence="evidenceById.get(activity.evidence_id)!" :content-version="evidenceVersion" :workspace="workspace" />
          <small v-else>{{ activity.evidence_id ? t("来源证据暂不可用，请核对关联。") : t("此条活性尚未关联来源证据。") }}</small>
        </div>
      </article>
    </div>
    </template>
    <details v-if="compound" class="context-evidence-management" @toggle="manageEvidence = ($event.target as HTMLDetailsElement).open">
      <summary>{{ t("管理活性来源证据") }}</summary>
      <p>{{ t("在此维护来源证据，然后在对应 Activity 的编辑表单中选择 Evidence。共享证据的修改会影响所有引用。") }}</p>
      <EvidenceEditor v-if="manageEvidence" :workspace="{ ...workspace, version: localVersion }" :evidence-ids="activityEvidenceIds" :activity-only="true" :read-only="readOnly" @mutated="evidenceMutation" @conflict="emit('conflict')" />
    </details>
  </section>
</template>

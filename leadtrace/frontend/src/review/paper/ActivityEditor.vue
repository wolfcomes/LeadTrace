<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import { ApiError } from "../../api/client";
import { useAuthStore } from "../../auth/store";
import { createActivity, deleteActivity, listActivities, listCompounds, listEvidence, updateActivity } from "../../v2/api";
import type { Activity, Compound, Evidence, PaperWorkspace } from "../../v2/types";

const props = defineProps<{ workspace: PaperWorkspace; selectedEntityId?: string; readOnly?: boolean }>();
const emit = defineEmits<{ select: [entityId: string]; mutated: [workspaceVersion: number]; conflict: [] }>();
const auth = useAuthStore();
const compounds = ref<Compound[]>([]);
const evidenceItems = ref<Evidence[]>([]);
const activities = ref<Activity[]>([]);
const localVersion = ref(props.workspace.version);
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
const error = ref("");

const compoundById = computed(() => new Map(compounds.value.map((compound) => [compound.id, compound])));

watch(() => props.workspace.version, (version) => {
  if (version > localVersion.value) localVersion.value = version;
});
watch(() => props.workspace.id, () => { void load(); });

function mutationError(reason: unknown, fallback: string): void {
  if (reason instanceof ApiError && reason.code === "WORKSPACE_VERSION_CONFLICT") {
    emit("conflict");
    error.value = "Workspace 已更新，正在重新载入全部 Activity 数据。";
    return;
  }
  error.value = fallback;
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const [compoundResult, evidenceResult] = await Promise.all([
      listCompounds(props.workspace.id),
      listEvidence(props.workspace.id),
    ]);
    compounds.value = compoundResult.items;
    evidenceItems.value = evidenceResult.items;
    compoundId.value = compounds.value[0]?.id ?? "";
    const activityResults = await Promise.all(compounds.value.map((compound) => listActivities(compound.id)));
    activities.value = activityResults.flatMap((result) => result.items);
    localVersion.value = Math.max(
      compoundResult.workspace_version,
      evidenceResult.workspace_version,
      ...activityResults.map((result) => result.workspace_version),
    );
  } catch {
    error.value = "Activity 数据暂时无法读取。";
  } finally {
    loading.value = false;
  }
}

function resetForm(): void {
  evidenceId.value = "";
  assayName.value = "";
  metric.value = "IC50";
  operator.value = "=";
  value.value = "";
  unit.value = "";
  context.value = "";
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
    }, auth.csrfToken);
    activities.value = [...activities.value, result.activity];
    localVersion.value = result.workspace_version;
    resetForm();
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
    localVersion.value = result.workspace_version;
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
    }, auth.csrfToken);
    activities.value = activities.value.map((item) => item.id === activityId ? result.activity : item);
    localVersion.value = result.workspace_version;
    cancelActivityEdit();
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
  <section class="activity-editor">
    <header class="section-heading"><div><p class="eyebrow">ACTIVITIES</p><h2>活性数据</h2></div><button class="button-secondary" data-add-activity type="button" :disabled="readOnly || busy || compounds.length === 0" @click="showCreate = !showCreate">添加 Activity</button></header>
    <form v-if="showCreate" class="activity-create-form inline-create-form" @submit.prevent="save">
      <label class="form-field">Compound<select v-model="compoundId" :disabled="readOnly || busy"><option v-for="compound in compounds" :key="compound.id" :value="compound.id">{{ compound.compound_label }}</option></select></label>
      <label class="form-field">Assay<input v-model="assayName" required maxlength="512" :disabled="readOnly || busy"></label>
      <label class="form-field">Metric<input v-model="metric" required maxlength="128" :disabled="readOnly || busy"></label>
      <label class="form-field">Operator<select v-model="operator" :disabled="readOnly || busy"><option value="=">=</option><option value="<">&lt;</option><option value="<=">≤</option><option value=">">&gt;</option><option value=">=">≥</option><option value="~">~</option></select></label>
      <label class="form-field">Value<input v-model="value" required inputmode="decimal" :disabled="readOnly || busy"></label>
      <label class="form-field">Unit<input v-model="unit" maxlength="128" :disabled="readOnly || busy"></label>
      <label class="form-field">Evidence<select v-model="evidenceId" :disabled="readOnly || busy"><option value="">无</option><option v-for="item in evidenceItems" :key="item.id" :value="item.id">p{{ item.page_number }} · {{ item.quoted_text || item.caption || item.kind }}</option></select></label>
      <label class="form-field">Context<input v-model="context" maxlength="10000" :disabled="readOnly || busy"></label>
      <button class="button-primary" type="button" :disabled="busy || !compoundId || !assayName.trim() || !metric.trim() || !value.trim()" @click="save">保存 Activity</button>
    </form>
    <form v-if="editingActivityId" class="activity-edit-form inline-create-form" @submit.prevent="saveActivityEdit">
      <label class="form-field">Assay<input v-model="editAssayName" required maxlength="512" :disabled="busy"></label>
      <label class="form-field">Metric<input v-model="editMetric" required maxlength="128" :disabled="busy"></label>
      <label class="form-field">Operator<select v-model="editOperator" :disabled="busy"><option value="=">=</option><option value="<">&lt;</option><option value="<=">≤</option><option value=">">&gt;</option><option value=">=">≥</option><option value="~">~</option></select></label>
      <label class="form-field">Value<input v-model="editValue" data-edit-activity-value required inputmode="decimal" :disabled="busy"></label>
      <label class="form-field">Unit<input v-model="editUnit" maxlength="128" :disabled="busy"></label>
      <label class="form-field">Evidence<select v-model="editEvidenceId" :disabled="busy"><option value="">无</option><option v-for="item in evidenceItems" :key="item.id" :value="item.id">p{{ item.page_number }} · {{ item.quoted_text || item.caption || item.kind }}</option></select></label>
      <label class="form-field">Context<input v-model="editContext" maxlength="10000" :disabled="busy"></label>
      <div class="editor-actions"><button class="button-primary" data-save-activity-edit type="button" :disabled="busy || !editAssayName.trim() || !editMetric.trim() || !editValue.trim()" @click="saveActivityEdit">保存修改</button><button class="button-quiet" type="button" :disabled="busy" @click="cancelActivityEdit">取消</button></div>
    </form>
    <p v-if="error" class="inline-feedback is-error" role="alert">{{ error }}</p>
    <p v-if="loading" class="workspace-empty-copy">正在读取 Activity…</p>
    <p v-else-if="activities.length === 0" class="workspace-empty-copy">当前尚无 Activity；如果文章没有报告活性，可将固定区段标记为“未报告”。</p>
    <div v-else class="activity-table" role="table" aria-label="Activity 条目">
      <article v-for="activity in activities" :key="activity.id" data-activity-row :class="{ selected: activity.id === selectedEntityId }" role="row" @click="emit('select', activity.id)">
        <strong>{{ compoundById.get(activity.compound_id)?.compound_label || "?" }}</strong><span>{{ activity.assay_name }}</span><span>{{ activity.metric }}</span><code>{{ activity.operator }} {{ activity.value }} {{ activity.unit || "" }}</code><small>{{ activity.context || "—" }}</small><div v-if="!readOnly" class="editor-actions"><button class="button-quiet" data-edit-activity type="button" :disabled="busy" @click.stop="startActivityEdit(activity)">编辑</button><button class="button-quiet" type="button" :disabled="busy" @click.stop="remove(activity)">删除</button></div>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import FieldExample from "./FieldExample.vue";
import ViewState from "./ViewState.vue";
import { useReviewProgress } from "./useReviewProgress";
import { t } from "../../i18n";
import { computed, nextTick, onMounted, ref, watch } from "vue";

import { ApiError } from "../../api/client";
import { useAuthStore } from "../../auth/store";
import {
  addLineageMember,
  createLineage,
  createLineageEdge,
  deleteLineage,
  deleteLineageEdge,
  deleteLineageMember,
  listCompounds,
  listEvidence,
  listEvidenceLinks,
  listLineages,
  updateLineage,
  updateLineageEdge,
  updateLineageMember,
} from "../../v2/api";
import type { Evidence, EvidenceLink, Compound, Lineage, LineageEdge, LineageMember, PaperWorkspace } from "../../v2/types";
import { lineageTypeLabels, type LineageType } from "../../v2/types";
import EvidenceEditor from "./EvidenceEditor.vue";
import EvidenceExcerpt from "./EvidenceExcerpt.vue";
import EdgeCompoundCard from "./EdgeCompoundCard.vue";
import { useLineageStructures } from "./useLineageStructures";
import EdgeEditor from "./EdgeEditor.vue";
import LineageGraph from "./LineageGraph.vue";

const props = defineProps<{ workspace: PaperWorkspace; selectedEntityId?: string; selectedGroupType?: LineageType; active?: boolean; readOnly?: boolean }>();
const emit = defineEmits<{ select: [entityId: string | undefined, group?: LineageType]; mutated: [workspaceVersion: number]; conflict: [] }>();
const auth = useAuthStore();
const progress = useReviewProgress();
const compounds = ref<Compound[]>([]);
const lineages = ref<Lineage[]>([]);
const selectedLineageId = ref<string>();
const selectedGroup = ref<LineageType>("sar");
const groupTypes: LineageType[] = ["sar", "synthesis", "unspecified"];
const filteredLineages = computed(() => lineages.value.filter(item => item.lineage_type === selectedGroup.value));
const lineageType = ref<LineageType>("sar");
const editLineageType = ref<LineageType>("unspecified");
const selectedEdgeId = ref<string>();
const activeView = ref<'graph' | 'compounds' | 'edges'>('graph');
const graphNodePicker = ref(false);
const pickerDialog = ref<HTMLDialogElement>();
watch(graphNodePicker, async open => {
  await nextTick();
  if (open) {
    if (typeof pickerDialog.value?.showModal === 'function') pickerDialog.value.showModal();
    else pickerDialog.value?.setAttribute('open','');
  } else pickerDialog.value?.close?.();
});
const selectedMemberId = ref<string>();
const graphCompoundSearch = ref('');
const edgeDraft = ref<{ parent: string; child: string; nonce: number }>();
const viewTabs = [{key: 'graph', label: '关系图'}, {key: 'compounds', label: 'Compound'}, {key: 'edges', label: 'Edge'}] as const;
function prepareEdge(parent: string, child: string): void {
  selectedEdgeId.value = undefined;
  edgeDraft.value = { parent, child, nonce: Date.now() };
  activeView.value = 'edges';
}
function openMember(id: string): void {
  selectedMemberId.value = id;
  activeView.value = 'compounds';
  void nextTick(() => document.getElementById('lineage-member-' + id)?.scrollIntoView?.({ block: 'nearest' }));
}

const mainPanel = ref<HTMLElement | null>(null);
const localVersion = ref(props.workspace.version);
let loadedVersion = props.workspace.version;
let initialized = false;
const refreshing = ref(false);
watch(() => props.active, active => { if (active && loadedVersion !== props.workspace.version) { invalidateStructures(); void load(); } });
const loading = ref(true);
const busy = ref(false);
const showCreate = ref(false);
const lineageLabel = ref("");
const lineageDescription = ref("");
const editingLineageId = ref<string>();
const editLineageLabel = ref("");
const editLineageDescription = ref("");
const newMemberCompoundId = ref("");
const newMemberRole = ref<LineageMember["role"]>("unspecified");
const error = ref("");
const evidenceItems = ref<Evidence[]>([]);
const evidenceVersion = ref(props.workspace.version);
const evidenceLinks = ref<EvidenceLink[]>([]);
const evidenceError = ref("");
const evidenceLoading = ref(false);
const managingEdgeId = ref<string>();
const showEvidenceLibrary = ref(false);
const evidenceById = computed(() => new Map(evidenceItems.value.map(item => [item.id, item])));
function linksForEdge(edgeId: string): EvidenceLink[] { return evidenceLinks.value.filter(link => link.edge_id === edgeId); }
function evidenceMutation(version: number): void { localVersion.value = version; loadedVersion = version; void loadEvidence(); emit("mutated", version); }
async function loadEvidence(): Promise<void> {
  evidenceLoading.value = true;
  evidenceError.value = "";
  try {
    const [catalog, ...linkResults] = await Promise.all([
      listEvidence(props.workspace.id),
      ...lineages.value.flatMap(lineage => lineage.edges.map(edge => listEvidenceLinks(edge.id))),
    ]);
    evidenceItems.value = catalog.items;
    evidenceVersion.value = catalog.workspace_version;
    evidenceLinks.value = linkResults.flatMap(result => result.items);
    localVersion.value = Math.max(localVersion.value, catalog.workspace_version, ...linkResults.map(result => result.workspace_version));
    const evidenceEdge = evidenceLinks.value.find(link => link.evidence_id === props.selectedEntityId);
    if (evidenceEdge) selectAddressedRecord(evidenceEdge.edge_id);
    else if (catalog.items.some(item => item.id === props.selectedEntityId)) showEvidenceLibrary.value = true;
  } catch { evidenceError.value = "Edge 证据暂时无法读取，请重试。"; }
  finally { evidenceLoading.value = false; }
}

const selectedLineage = computed(() => lineages.value.find((lineage) => lineage.id === selectedLineageId.value));
const selectedEdge = computed(() => selectedLineage.value?.edges.find(edge => edge.id === selectedEdgeId.value));
const displayedLineage = computed(() => selectedLineage.value && selectedEdge.value ? { ...selectedLineage.value, edges: [selectedEdge.value] } : selectedLineage.value);
const structureCompoundIds = computed(() => selectedLineage.value?.members.map(member => member.compound_id) ?? []);
const { records: structureRecords, retry: retryStructure, invalidate: invalidateStructures } = useLineageStructures(() => props.workspace.id, structureCompoundIds);
watch(selectedEdgeId, async () => {
  managingEdgeId.value = undefined;
  await nextTick();
  mainPanel.value?.focus({ preventScroll: true });
  mainPanel.value?.scrollIntoView?.({ block: 'start' });
});
function openEdge(edgeId: string): void {
  if (!selectedLineage.value?.edges.some(edge => edge.id === edgeId)) return;
  if (!refreshing.value) void progress?.view('lineage',selectedLineage.value.id,true,loadedVersion); activeView.value = 'edges'; selectedEdgeId.value = edgeId; emit('select', edgeId);
}
function returnToGraph(): void {
  activeView.value = 'graph';
  selectedEdgeId.value = undefined;
  if (selectedLineage.value) emit('select', selectedLineage.value.id);
}
const compoundById = computed(() => new Map(compounds.value.map((compound) => [compound.id, compound])));
const availableCompounds = computed(() => {
  const members = new Set(selectedLineage.value?.members.map((member) => member.compound_id) ?? []);
  return compounds.value.filter((compound) => !members.has(compound.id));
});

watch(() => props.workspace.version, (version) => {
  if (version > localVersion.value) localVersion.value = version;
  if (initialized && props.active !== false && version !== loadedVersion) { invalidateStructures(); void load(); }
});
watch(() => props.workspace.id, () => { void load(); });
watch(() => [props.selectedEntityId, props.selectedGroupType], () => selectAddressedRecord(props.selectedEntityId));
watch(availableCompounds, (items) => {
  if (!items.some((item) => item.id === newMemberCompoundId.value)) newMemberCompoundId.value = items[0]?.id ?? "";
}, { immediate: true });

function selectAddressedRecord(entityId?: string): void {
  if (!entityId) {
    selectedGroup.value = props.selectedGroupType ?? (lineages.value.find(item => item.lineage_type === "sar") ?? lineages.value[0])?.lineage_type ?? "sar";
    selectedLineageId.value = filteredLineages.value[0]?.id;
    selectedEdgeId.value = undefined;
    return;
  }
  const lineage = lineages.value.find((item) => item.id === entityId
    || item.members.some((member) => member.id === entityId || member.compound_id === entityId)
    || item.edges.some((edge) => edge.id === entityId));
  if (lineage) {
    selectedLineageId.value = lineage.id;
    selectedGroup.value = lineage.lineage_type;
    selectedEdgeId.value = lineage.edges.find(edge => edge.id === entityId)?.id;
    if (selectedEdgeId.value) activeView.value = 'edges';
  }
}

function selectLineage(lineage: Lineage): void {
  if (!refreshing.value) void progress?.view("lineage",lineage.id,true,loadedVersion);
  selectedLineageId.value = lineage.id;
  selectedGroup.value = lineage.lineage_type;
  selectedEdgeId.value = undefined;
  emit("select", lineage.id, lineage.lineage_type);
}

function selectGroup(type: LineageType): void {
  selectedGroup.value = type;
  selectedEdgeId.value = undefined;
  selectedLineageId.value = filteredLineages.value[0]?.id;
  lineageType.value = type === "unspecified" ? "sar" : type;
  cancelLineageEdit();
  emit("select", selectedLineageId.value, selectedGroup.value);
}

function startLineageEdit(lineage: Lineage): void {
  editingLineageId.value = lineage.id;
  editLineageLabel.value = lineage.lineage_label;
  editLineageType.value = lineage.lineage_type;
  editLineageDescription.value = lineage.description ?? "";
}

function cancelLineageEdit(): void {
  editingLineageId.value = undefined;
  editLineageLabel.value = "";
  editLineageDescription.value = "";
}

function mutationError(reason: unknown, fallback: string): void {
  if (reason instanceof ApiError && reason.code === "WORKSPACE_VERSION_CONFLICT") {
    emit("conflict");
    error.value = "Workspace 已更新，正在重新载入全部 Lineage 数据。";
    return;
  }
  error.value = fallback;
}

async function load(): Promise<void> {
  if (!initialized) loading.value = true;
  refreshing.value = true;
  error.value = "";
  try {
    const [compoundResult, lineageResult] = await Promise.all([
      listCompounds(props.workspace.id),
      listLineages(props.workspace.id),
    ]);
    loadedVersion = Math.min(compoundResult.workspace_version,lineageResult.workspace_version); initialized = true;
    compounds.value = compoundResult.items;
    lineages.value = lineageResult.items;
    void loadEvidence();
    localVersion.value = Math.max(compoundResult.workspace_version, lineageResult.workspace_version);
    selectAddressedRecord(props.selectedEntityId);
    if (props.selectedEntityId && (!selectedLineageId.value || !lineages.value.some((item) => item.id === selectedLineageId.value))) {
      const first = lineages.value.find(item => item.lineage_type === "sar") ?? lineages.value[0];
      selectedLineageId.value = first?.id;
      selectedGroup.value = first?.lineage_type ?? "sar";
    }
  } catch {
    error.value = "Lineage 数据暂时无法读取。";
  } finally {
    loading.value = false;
    refreshing.value = false;
  }
}

async function create(): Promise<void> {
  if (!lineageLabel.value.trim() || props.readOnly || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await createLineage(props.workspace.id, {
      expected_workspace_version: localVersion.value,
      lineage_label: lineageLabel.value.trim(),
      lineage_type: lineageType.value,
      description: lineageDescription.value.trim() || null,
    }, auth.csrfToken);
    lineages.value = [...lineages.value, result.lineage];
    selectedLineageId.value = result.lineage.id;
    selectedGroup.value = result.lineage.lineage_type;
    selectedEdgeId.value = undefined;
    localVersion.value = result.workspace_version; loadedVersion = result.workspace_version;
    lineageLabel.value = "";
    lineageDescription.value = "";
    showCreate.value = false;
    emit("select", result.lineage.id, result.lineage.lineage_type);
    emit("mutated", result.workspace_version);
  } catch (reason) {
    mutationError(reason, "Lineage 未能创建，请重试。");
  } finally {
    busy.value = false;
  }
}

async function removeLineage(lineage: Lineage): Promise<void> {
  if (props.readOnly || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await deleteLineage(lineage.id, localVersion.value, auth.csrfToken);
    lineages.value = lineages.value.filter((item) => item.id !== lineage.id);
    selectedLineageId.value = filteredLineages.value[0]?.id;
    selectedEdgeId.value = undefined;
    emit("select", selectedLineageId.value, selectedGroup.value);
    localVersion.value = result.workspace_version; loadedVersion = result.workspace_version;
    emit("mutated", result.workspace_version);
  } catch (reason) {
    mutationError(reason, "Lineage 未能删除；请先清理其 Member 和 Edge。");
  } finally {
    busy.value = false;
  }
}

async function saveLineageEdit(): Promise<void> {
  const lineageId = editingLineageId.value;
  if (!lineageId || !editLineageLabel.value.trim() || props.readOnly || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await updateLineage(lineageId, {
      expected_workspace_version: localVersion.value,
      lineage_label: editLineageLabel.value.trim(),
      lineage_type: editLineageType.value,
      description: editLineageDescription.value.trim() || null,
    }, auth.csrfToken);
    lineages.value = lineages.value.map((item) => item.id === lineageId ? result.lineage : item);
    localVersion.value = result.workspace_version; loadedVersion = result.workspace_version;
    selectLineage(result.lineage);
    cancelLineageEdit();
    emit("mutated", result.workspace_version);
  } catch (reason) {
    mutationError(reason, "Lineage 修改未能保存，请重试。");
  } finally {
    busy.value = false;
  }
}

async function addMember(): Promise<void> {
  const lineage = selectedLineage.value;
  if (!lineage || !newMemberCompoundId.value || props.readOnly || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await addLineageMember(lineage.id, {
      expected_workspace_version: localVersion.value,
      compound_id: newMemberCompoundId.value,
      role: newMemberRole.value,
    }, auth.csrfToken);
    lineage.members = [...lineage.members, result.member];
    localVersion.value = result.workspace_version; loadedVersion = result.workspace_version;
    newMemberRole.value = "unspecified";
    graphNodePicker.value = false;
    emit("mutated", result.workspace_version);
  } catch (reason) {
    mutationError(reason, "Member 未能添加，请重试。");
  } finally {
    busy.value = false;
  }
}

async function changeMemberRole(member: LineageMember, role: LineageMember["role"]): Promise<void> {
  if (props.readOnly || busy.value || role === member.role) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await updateLineageMember(member.id, { expected_workspace_version: localVersion.value, role }, auth.csrfToken);
    const lineage = selectedLineage.value;
    if (lineage) lineage.members = lineage.members.map((item) => item.id === member.id ? result.member : item);
    localVersion.value = result.workspace_version; loadedVersion = result.workspace_version;
    emit("mutated", result.workspace_version);
  } catch (reason) {
    mutationError(reason, "Member 角色未能更新，请重试。");
  } finally {
    busy.value = false;
  }
}

async function removeMember(member: LineageMember): Promise<void> {
  if (props.readOnly || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await deleteLineageMember(member.id, localVersion.value, auth.csrfToken);
    const lineage = selectedLineage.value;
    if (lineage) lineage.members = lineage.members.filter((item) => item.id !== member.id);
    localVersion.value = result.workspace_version; loadedVersion = result.workspace_version;
    emit("mutated", result.workspace_version);
  } catch (reason) {
    mutationError(reason, "该 Member 仍被 Edge 引用，无法删除。");
  } finally {
    busy.value = false;
  }
}

async function addEdge(payload: { parentCompoundId: string; childCompoundId: string; relationType: string; modificationSummary: string | null; reviewHint?: string | null; reviewStatus: LineageEdge["review_status"] }): Promise<void> {
  const lineage = selectedLineage.value;
  if (!lineage || props.readOnly || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await createLineageEdge(lineage.id, {
      expected_workspace_version: localVersion.value,
      parent_compound_id: payload.parentCompoundId,
      child_compound_id: payload.childCompoundId,
      relation_type: payload.relationType,
      modification_summary: payload.modificationSummary,
      review_hint: payload.reviewHint,
      review_status: payload.reviewStatus,
    }, auth.csrfToken);
    lineage.edges = [...lineage.edges, result.edge];
    localVersion.value = result.workspace_version; loadedVersion = result.workspace_version;
    emit("mutated", result.workspace_version);
  } catch (reason) {
    mutationError(reason, "Edge 未能创建；请检查端点和重复关系。");
  } finally {
    busy.value = false;
  }
}

async function updateEdge(edge: LineageEdge, payload: {
  parentCompoundId?: string;
  childCompoundId?: string;
  relationType?: string;
  modificationSummary?: string | null;
  reviewHint?: string | null;
  reviewStatus?: LineageEdge["review_status"];
}): Promise<void> {
  if (props.readOnly || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await updateLineageEdge(edge.id, {
      expected_workspace_version: localVersion.value,
      ...(payload.parentCompoundId ? { parent_compound_id: payload.parentCompoundId } : {}),
      ...(payload.childCompoundId ? { child_compound_id: payload.childCompoundId } : {}),
      ...(payload.relationType ? { relation_type: payload.relationType } : {}),
      ...(payload.modificationSummary !== undefined ? { modification_summary: payload.modificationSummary } : {}),
      ...(payload.reviewHint !== undefined ? { review_hint: payload.reviewHint } : {}),
      ...(payload.reviewStatus ? { review_status: payload.reviewStatus } : {}),
    }, auth.csrfToken);
    const lineage = selectedLineage.value;
    if (lineage) lineage.edges = lineage.edges.map((item) => item.id === edge.id ? result.edge : item);
    localVersion.value = result.workspace_version; loadedVersion = result.workspace_version;
    emit("mutated", result.workspace_version);
  } catch (reason) {
    mutationError(reason, "Edge 状态未能更新，请重试。");
  } finally {
    busy.value = false;
  }
}

async function removeEdge(edge: LineageEdge): Promise<void> {
  if (props.readOnly || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await deleteLineageEdge(edge.id, localVersion.value, auth.csrfToken);
    const lineage = lineages.value.find((item) => item.id === edge.lineage_id);
    if (lineage) lineage.edges = lineage.edges.filter((item) => item.id !== edge.id);
    localVersion.value = result.workspace_version; loadedVersion = result.workspace_version;
    emit("mutated", result.workspace_version);
  } catch (reason) {
    mutationError(reason, "Edge 未能删除，请重试。");
  } finally {
    busy.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section class="lineage-workspace">
    <header class="section-heading"><div><p class="eyebrow">LINEAGES</p><h2>{{ t("SAR 与合成路线") }}</h2></div><button class="button-primary" data-add-lineage type="button" :disabled="readOnly || busy" @click="showCreate = !showCreate">{{ t("添加 Lineage") }}</button></header>
    <FieldExample section="lineages" />
    <nav class="lineage-group-switch" :aria-label='t("Lineage 类别")'>
      <button v-for="type in groupTypes" :key="type" type="button" class="button-secondary" :data-lineage-group="type" :aria-pressed="selectedGroup === type" @click="selectGroup(type)">{{ t(lineageTypeLabels[type]) }} <span>{{ lineages.filter(item => item.lineage_type === type).length }}</span></button>
    </nav>
    <p class="lineage-group-description" data-lineage-group-description>{{ selectedGroup === 'sar' ? t("围绕结构变化、设计思路与活性比较组织关系；不表示实际合成步骤。") : selectedGroup === 'synthesis' ? t("根据合成 Scheme 和实验方法记录前体到产物的转化或多步合成路径；具体步骤见关系说明与证据。") : t("这些记录尚未确认属于 SAR 还是化学合成，请核对后分类。") }}</p>
    <form v-if="showCreate" class="inline-create-form" @submit.prevent="create">
      <label class="form-field">{{ t("类别") }}<select v-model="lineageType" data-lineage-type-input class="form-control"><option value="sar">{{ t("SAR / 结构优化") }}</option><option value="synthesis">{{ t("化学合成") }}</option></select></label>
      <label class="form-field">Lineage label<input v-model="lineageLabel" :placeholder="t('例如：Series A — scaffold optimization')" data-lineage-label-input class="form-control" required maxlength="255"></label>
      <label class="form-field">{{ t("描述") }}<input v-model="lineageDescription" :placeholder="t('说明起点、变化主线、终点及依据')" class="form-control" maxlength="10000"></label>
      <button class="button-primary" data-save-lineage type="button" :disabled="busy || !lineageLabel.trim()" @click="create">{{ t("保存 Lineage") }}</button>
    </form>
    <form v-if="editingLineageId" class="inline-create-form" @submit.prevent="saveLineageEdit">
      <label class="form-field">{{ t("类别") }}<select v-model="editLineageType" data-edit-lineage-type class="form-control"><option v-for="type in groupTypes" :key="type" :value="type">{{ t(lineageTypeLabels[type]) }}</option></select></label>
      <label class="form-field">Lineage label<input v-model="editLineageLabel" data-edit-lineage-label class="form-control" required maxlength="255"></label>
      <label class="form-field">{{ t("描述") }}<input v-model="editLineageDescription" class="form-control" maxlength="10000"></label>
      <div class="editor-actions"><button class="button-primary" data-save-lineage-edit type="button" :disabled="busy || !editLineageLabel.trim()" @click="saveLineageEdit">{{ t("保存修改") }}</button><button class="button-quiet" type="button" :disabled="busy" @click="cancelLineageEdit">{{ t("取消") }}</button></div>
    </form>
    <p v-if="error" class="inline-feedback is-error" role="alert">{{ t(error) }}</p>
    <p v-if="loading" class="workspace-empty-copy">{{ t("正在读取 Lineage…") }}</p>
    <p v-else-if="filteredLineages.length === 0" class="workspace-empty-copy">{{ t("当前分类尚无 Lineage。可根据文章添加 SAR 或合成路线。") }}</p>
    <div v-else class="lineage-editor-layout">
      <aside class="lineage-list-panel" :aria-label='t("Lineage 列表")'>
        <article v-for="lineage in filteredLineages" :key="lineage.id" data-lineage-card :data-lineage-id="lineage.id" :class="{ selected: lineage.id === selectedLineageId }">
          <button type="button" @click="selectLineage(lineage)"><strong>{{ lineage.lineage_label }}</strong><ViewState compact kind="lineage" :entity-id="lineage.id" /><small>{{ lineage.members.length }} members · {{ lineage.edges.length }} edges</small></button>
          <div class="lineage-member-summary">
            <span v-for="member in lineage.members" :key="member.id" :data-member-role="member.role">{{ compoundById.get(member.compound_id)?.compound_label || "?" }} · {{ member.role }}</span>
          </div>
          <div v-if="!readOnly" class="editor-actions"><button class="button-quiet" data-edit-lineage type="button" :disabled="busy" @click="startLineageEdit(lineage)">{{ t("编辑") }}</button><button class="button-quiet" type="button" :disabled="busy" @click="removeLineage(lineage)">{{ t("删除") }}</button></div>
        </article>
      </aside>
      <div v-if="selectedLineage" ref="mainPanel" class="lineage-detail-panel lineage-main-panel" tabindex="-1" :data-edge-detail="selectedEdge ? '' : undefined" :data-selected-edge-id="selectedEdge?.id">
        <header class="lineage-main-heading">
          <div><span class="status-chip" data-lineage-type>{{ t(lineageTypeLabels[selectedLineage.lineage_type]) }}</span><p class="eyebrow">{{ activeView === 'edges' && selectedEdge ? 'EDGE DETAIL' : 'LINEAGE' }}</p><h3>{{ activeView === 'edges' && selectedEdge ? `${compoundById.get(selectedEdge.parent_compound_id)?.compound_label || '?'} → ${compoundById.get(selectedEdge.child_compound_id)?.compound_label || '?'}` : selectedLineage.lineage_label }}</h3><p v-if="activeView === 'edges' && selectedEdge">{{ selectedLineage.lineage_label }} · {{ selectedEdge.relation_type }}</p></div>
          <button v-if="activeView === 'edges' && selectedEdge" class="button-secondary" data-return-lineage type="button" @click="returnToGraph">{{ t("← 返回关系图") }}</button>
        </header>
        <ViewState kind="lineage" :entity-id="selectedLineage.id" />
        <p v-if="activeView !== 'edges' && selectedLineage.description" class="lineage-description">{{ selectedLineage.description }}</p>
        <nav class="workspace-tabs lineage-view-tabs" role="tablist" :aria-label="t('Lineage 视图')">
          <button v-for="tab in viewTabs" :key="tab.key" type="button" role="tab" :data-lineage-view-tab="tab.key" :aria-selected="activeView === tab.key" @click="activeView = tab.key">{{ t(tab.label) }}</button>
        </nav>
        <div v-show="activeView === 'graph'" data-lineage-view="graph">
          <LineageGraph :lineage="selectedLineage" :compounds="compounds" :structures="structureRecords" :visible="activeView === 'graph'" :read-only="readOnly" @select-edge="openEdge" @select-node="openMember" @add-node="graphNodePicker = true; newMemberCompoundId = ''; graphCompoundSearch = ''" @connect="prepareEdge" />
          <dialog v-if="graphNodePicker" ref="pickerDialog" class="graph-compound-dialog" :aria-label="t('将已有 Compound 加入本 Lineage')" @cancel="graphNodePicker = false"><form class="graph-compound-picker" data-graph-compound-picker @submit.prevent="addMember" @keydown.esc="graphNodePicker = false">
            <h4>{{ t('将已有 Compound 加入本 Lineage') }}</h4>
            <p>{{ t('请选择本篇文章的 Compound；此操作不会创建新的化合物记录。') }}</p>
            <label class="form-field">{{ t('搜索编号或名称') }}<input v-model="graphCompoundSearch" :placeholder="t('例如：24 或 reference')"></label>
            <label class="form-field">Compound<select v-model="newMemberCompoundId" data-graph-compound-select required :disabled="busy"><option value="">{{ t('选择编号') }}</option><option v-for="compound in availableCompounds.filter(c => (c.compound_label + ' ' + (c.display_name || '')).toLowerCase().includes(graphCompoundSearch.toLowerCase()))" :key="compound.id" :value="compound.id">{{ compound.compound_label }} · {{ compound.display_name || t('未命名') }}</option></select></label>
            <label class="form-field">{{ t('角色') }}<select v-model="newMemberRole" :disabled="busy"><option value="unspecified">Unspecified</option><option value="root">Root</option><option value="intermediate">Intermediate</option><option value="terminal">Terminal</option></select></label>
            <p v-if="!availableCompounds.length">{{ t('没有可添加的 Compound。请先到“化合物与结构”创建记录，或检查是否已加入。') }}</p>
            <div class="dialog-actions"><button type="submit" class="button-primary" data-confirm-graph-node :disabled="readOnly || busy || !newMemberCompoundId">{{ t('添加 Node') }}</button>
            <button type="button" class="button-quiet" data-cancel-graph-node :disabled="busy" @click="graphNodePicker = false">{{ t('取消') }}</button></div>
          </form></dialog>
        </div>
        <div v-if="selectedEdge" v-show="activeView === 'edges'" class="edge-endpoint-pair">
          <EdgeCompoundCard :compound="compoundById.get(selectedEdge.parent_compound_id)" :compound-id="selectedEdge.parent_compound_id" :state="structureRecords[selectedEdge.parent_compound_id]" :workspace-id="workspace.id" :paper-id="workspace.bibliography.paper_id" :caption="selectedLineage.lineage_type === 'synthesis' ? t('反应前体 / 路径起点') : selectedLineage.lineage_type === 'sar' || selectedEdge.relation_type === 'sar_baseline_comparison' ? t('比较基线 / 设计起点') : t('起点 / Parent')" @retry="retryStructure" />
          <EdgeCompoundCard :compound="compoundById.get(selectedEdge.child_compound_id)" :compound-id="selectedEdge.child_compound_id" :state="structureRecords[selectedEdge.child_compound_id]" :workspace-id="workspace.id" :paper-id="workspace.bibliography.paper_id" :caption="selectedLineage.lineage_type === 'synthesis' ? t('产物 / 路径终点') : selectedLineage.lineage_type === 'sar' || selectedEdge.relation_type === 'sar_baseline_comparison' ? t('被比较化合物') : t('终点 / Child')" @retry="retryStructure" />
        </div>
        <section v-show="activeView === 'compounds'" class="member-editor" data-lineage-view="compounds">
          <header class="compact-heading"><div><p class="eyebrow">MEMBERS</p><h4>{{ t("Compound 角色") }}</h4></div></header>
          <div class="member-list">
            <article v-for="member in selectedLineage.members" :key="member.id" class="member-row" :id="'lineage-member-' + member.compound_id">
              <button type="button" class="button-quiet" @click="selectedMemberId = member.compound_id">{{ compoundById.get(member.compound_id)?.compound_label || member.compound_id }}</button>
              <select :value="member.role" :disabled="readOnly || busy" @change="changeMemberRole(member, ($event.target as HTMLSelectElement).value as LineageMember['role'])"><option value="root">Root</option><option value="intermediate">Intermediate</option><option value="terminal">Terminal</option><option value="unspecified">Unspecified</option></select>
              <button class="button-quiet" type="button" :disabled="readOnly || busy" @click="removeMember(member)">{{ t("删除 Member") }}</button>
            </article>
          </div>
          <EdgeCompoundCard v-if="selectedMemberId && selectedLineage.members.some(m => m.compound_id === selectedMemberId)" :compound="compoundById.get(selectedMemberId)" :compound-id="selectedMemberId" :state="structureRecords[selectedMemberId]" :workspace-id="workspace.id" :paper-id="workspace.bibliography.paper_id" caption="Compound" @retry="retryStructure" />
          <form class="inline-create-form" @submit.prevent="addMember">
            <label class="form-field">Compound<select v-model="newMemberCompoundId" :disabled="readOnly || busy"><option v-for="compound in availableCompounds" :key="compound.id" :value="compound.id">{{ compound.compound_label }}</option></select></label>
            <label class="form-field">{{ t("角色") }}<select v-model="newMemberRole" :disabled="readOnly || busy"><option value="root">Root</option><option value="intermediate">Intermediate</option><option value="terminal">Terminal</option><option value="unspecified">Unspecified</option></select></label>
            <button class="button-secondary" type="submit" :disabled="readOnly || busy || !newMemberCompoundId">{{ t("添加 Member") }}</button>
          </form>
        </section>
        <div v-show="activeView === 'edges'" data-lineage-view="edges">
        <EdgeEditor v-if="displayedLineage" :draft-endpoints="edgeDraft" :lineage="displayedLineage" :focused-edge-id="selectedEdge?.id" :compounds="compounds" :read-only="readOnly" :busy="busy" @select="openEdge" @create="addEdge" @update="updateEdge" @delete="removeEdge">
          <template #evidence="{ edge }">
            <div class="edge-context-evidence" data-edge-context-evidence>
              <h5>{{ t("关系证据") }}</h5>
              <p v-if="evidenceLoading">{{ t("正在读取证据…") }}</p>
              <p v-else-if="evidenceError" role="alert">{{ t(evidenceError) }}<button type="button" class="button-quiet" @click="loadEvidence">{{ t("重试") }}</button></p>
              <template v-else>
                <div v-for="link in linksForEdge(edge.id)" :key="link.id" data-edge-evidence-link>
                  <span class="status-chip">{{ link.role }}</span>
                  <EvidenceExcerpt v-if="evidenceById.get(link.evidence_id)" :evidence="evidenceById.get(link.evidence_id)!" :content-version="evidenceVersion" :workspace="workspace" />
                  <p v-else>{{ t("关联证据暂不可用，请核对。") }}</p>
                </div>
                <p v-if="!linksForEdge(edge.id).length" class="evidence-empty">{{ t("尚未关联证据。允许依据 AI 对结构或 SAR 的判断保留此关系，请核对修改摘要中的推断理由。") }}</p>
              </template>
              <button v-if="!readOnly" class="button-quiet" data-manage-edge-evidence type="button" @click="managingEdgeId = managingEdgeId === edge.id ? undefined : edge.id">{{ managingEdgeId === edge.id ? t("收起证据编辑") : t("添加 / 编辑关系证据") }}</button>
              <EvidenceEditor v-if="managingEdgeId === edge.id" :key="edge.id" :workspace="{ ...workspace, version: localVersion }" :edge-id="edge.id" :read-only="readOnly" @mutated="evidenceMutation" @conflict="emit('conflict')" />
            </div>
          </template>
        </EdgeEditor>
        </div>
      </div>
    </div>
    <details class="context-evidence-management" :open="showEvidenceLibrary" @toggle="showEvidenceLibrary = ($event.target as HTMLDetailsElement).open">
      <summary>{{ t("全文证据库 / 未关联证据") }}</summary>
      <EvidenceEditor v-if="showEvidenceLibrary" :workspace="{ ...workspace, version: localVersion }" :selected-entity-id="selectedEntityId" :read-only="readOnly" @mutated="evidenceMutation" @conflict="emit('conflict')" />
    </details>
  </section>
</template>

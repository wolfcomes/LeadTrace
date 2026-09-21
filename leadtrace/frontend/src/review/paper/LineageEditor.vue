<script setup lang="ts">
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

const props = defineProps<{ workspace: PaperWorkspace; selectedEntityId?: string; selectedGroupType?: LineageType; readOnly?: boolean }>();
const emit = defineEmits<{ select: [entityId: string | undefined, group?: LineageType]; mutated: [workspaceVersion: number]; conflict: [] }>();
const auth = useAuthStore();
const compounds = ref<Compound[]>([]);
const lineages = ref<Lineage[]>([]);
const selectedLineageId = ref<string>();
const selectedGroup = ref<LineageType>("sar");
const groupTypes: LineageType[] = ["sar", "synthesis", "unspecified"];
const filteredLineages = computed(() => lineages.value.filter(item => item.lineage_type === selectedGroup.value));
const lineageType = ref<LineageType>("sar");
const editLineageType = ref<LineageType>("unspecified");
const selectedEdgeId = ref<string>();
const mainPanel = ref<HTMLElement | null>(null);
const localVersion = ref(props.workspace.version);
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
const evidenceLinks = ref<EvidenceLink[]>([]);
const evidenceError = ref("");
const evidenceLoading = ref(false);
const managingEdgeId = ref<string>();
const showEvidenceLibrary = ref(false);
const evidenceById = computed(() => new Map(evidenceItems.value.map(item => [item.id, item])));
function linksForEdge(edgeId: string): EvidenceLink[] { return evidenceLinks.value.filter(link => link.edge_id === edgeId); }
function evidenceMutation(version: number): void { localVersion.value = version; emit("mutated", version); }
async function loadEvidence(): Promise<void> {
  evidenceLoading.value = true;
  evidenceError.value = "";
  try {
    const [catalog, ...linkResults] = await Promise.all([
      listEvidence(props.workspace.id),
      ...lineages.value.flatMap(lineage => lineage.edges.map(edge => listEvidenceLinks(edge.id))),
    ]);
    evidenceItems.value = catalog.items;
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
const { records: structureRecords, retry: retryStructure } = useLineageStructures(() => props.workspace.id, structureCompoundIds);
watch(selectedEdgeId, async () => {
  managingEdgeId.value = undefined;
  await nextTick();
  mainPanel.value?.focus({ preventScroll: true });
  mainPanel.value?.scrollIntoView?.({ block: 'start' });
});
function openEdge(edgeId: string): void {
  if (!selectedLineage.value?.edges.some(edge => edge.id === edgeId)) return;
  selectedEdgeId.value = edgeId; emit('select', edgeId);
}
function returnToGraph(): void {
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
  }
}

function selectLineage(lineage: Lineage): void {
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
  loading.value = true;
  error.value = "";
  try {
    const [compoundResult, lineageResult] = await Promise.all([
      listCompounds(props.workspace.id),
      listLineages(props.workspace.id),
    ]);
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
    localVersion.value = result.workspace_version;
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
    localVersion.value = result.workspace_version;
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
    localVersion.value = result.workspace_version;
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
    localVersion.value = result.workspace_version;
    newMemberRole.value = "unspecified";
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
    localVersion.value = result.workspace_version;
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
    localVersion.value = result.workspace_version;
    emit("mutated", result.workspace_version);
  } catch (reason) {
    mutationError(reason, "该 Member 仍被 Edge 引用，无法删除。");
  } finally {
    busy.value = false;
  }
}

async function addEdge(payload: { parentCompoundId: string; childCompoundId: string; relationType: string; modificationSummary: string | null; reviewStatus: LineageEdge["review_status"] }): Promise<void> {
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
      review_status: payload.reviewStatus,
    }, auth.csrfToken);
    lineage.edges = [...lineage.edges, result.edge];
    localVersion.value = result.workspace_version;
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
      ...(payload.reviewStatus ? { review_status: payload.reviewStatus } : {}),
    }, auth.csrfToken);
    const lineage = selectedLineage.value;
    if (lineage) lineage.edges = lineage.edges.map((item) => item.id === edge.id ? result.edge : item);
    localVersion.value = result.workspace_version;
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
    localVersion.value = result.workspace_version;
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
    <header class="section-heading"><div><p class="eyebrow">LINEAGES</p><h2>SAR 与合成路线</h2></div><button class="button-primary" data-add-lineage type="button" :disabled="readOnly || busy" @click="showCreate = !showCreate">添加 Lineage</button></header>
    <nav class="lineage-group-switch" aria-label="Lineage 类别">
      <button v-for="type in groupTypes" :key="type" type="button" class="button-secondary" :data-lineage-group="type" :aria-pressed="selectedGroup === type" @click="selectGroup(type)">{{ lineageTypeLabels[type] }} <span>{{ lineages.filter(item => item.lineage_type === type).length }}</span></button>
    </nav>
    <p class="lineage-group-description" data-lineage-group-description>{{ selectedGroup === 'sar' ? '围绕结构变化、设计思路与活性比较组织关系；不表示实际合成步骤。' : selectedGroup === 'synthesis' ? '根据合成 Scheme 和实验方法记录前体到产物的转化或多步合成路径；具体步骤见关系说明与证据。' : '这些记录尚未确认属于 SAR 还是化学合成，请核对后分类。' }}</p>
    <form v-if="showCreate" class="inline-create-form" @submit.prevent="create">
      <label class="form-field">类别<select v-model="lineageType" data-lineage-type-input class="form-control"><option value="sar">SAR / 结构优化</option><option value="synthesis">化学合成</option></select></label>
      <label class="form-field">Lineage label<input v-model="lineageLabel" data-lineage-label-input class="form-control" required maxlength="255"></label>
      <label class="form-field">描述<input v-model="lineageDescription" class="form-control" maxlength="10000"></label>
      <button class="button-primary" data-save-lineage type="button" :disabled="busy || !lineageLabel.trim()" @click="create">保存 Lineage</button>
    </form>
    <form v-if="editingLineageId" class="inline-create-form" @submit.prevent="saveLineageEdit">
      <label class="form-field">类别<select v-model="editLineageType" data-edit-lineage-type class="form-control"><option v-for="type in groupTypes" :key="type" :value="type">{{ lineageTypeLabels[type] }}</option></select></label>
      <label class="form-field">Lineage label<input v-model="editLineageLabel" data-edit-lineage-label class="form-control" required maxlength="255"></label>
      <label class="form-field">描述<input v-model="editLineageDescription" class="form-control" maxlength="10000"></label>
      <div class="editor-actions"><button class="button-primary" data-save-lineage-edit type="button" :disabled="busy || !editLineageLabel.trim()" @click="saveLineageEdit">保存修改</button><button class="button-quiet" type="button" :disabled="busy" @click="cancelLineageEdit">取消</button></div>
    </form>
    <p v-if="error" class="inline-feedback is-error" role="alert">{{ error }}</p>
    <p v-if="loading" class="workspace-empty-copy">正在读取 Lineage…</p>
    <p v-else-if="filteredLineages.length === 0" class="workspace-empty-copy">当前分类尚无 Lineage。可根据文章添加 SAR 或合成路线。</p>
    <div v-else class="lineage-editor-layout">
      <aside class="lineage-list-panel" aria-label="Lineage 列表">
        <article v-for="lineage in filteredLineages" :key="lineage.id" data-lineage-card :data-lineage-id="lineage.id" :class="{ selected: lineage.id === selectedLineageId }">
          <button type="button" @click="selectLineage(lineage)"><strong>{{ lineage.lineage_label }}</strong><small>{{ lineage.members.length }} members · {{ lineage.edges.length }} edges</small></button>
          <div class="lineage-member-summary">
            <span v-for="member in lineage.members" :key="member.id" :data-member-role="member.role">{{ compoundById.get(member.compound_id)?.compound_label || "?" }} · {{ member.role }}</span>
          </div>
          <div v-if="!readOnly" class="editor-actions"><button class="button-quiet" data-edit-lineage type="button" :disabled="busy" @click="startLineageEdit(lineage)">编辑</button><button class="button-quiet" type="button" :disabled="busy" @click="removeLineage(lineage)">删除</button></div>
        </article>
      </aside>
      <div v-if="selectedLineage" ref="mainPanel" class="lineage-detail-panel lineage-main-panel" tabindex="-1" :data-edge-detail="selectedEdge ? '' : undefined" :data-selected-edge-id="selectedEdge?.id">
        <header class="lineage-main-heading">
          <div><span class="status-chip" data-lineage-type>{{ lineageTypeLabels[selectedLineage.lineage_type] }}</span><p class="eyebrow">{{ selectedEdge ? 'EDGE DETAIL' : 'LINEAGE' }}</p><h3>{{ selectedEdge ? `${compoundById.get(selectedEdge.parent_compound_id)?.compound_label || '?'} → ${compoundById.get(selectedEdge.child_compound_id)?.compound_label || '?'}` : selectedLineage.lineage_label }}</h3><p v-if="selectedEdge">{{ selectedLineage.lineage_label }} · {{ selectedEdge.relation_type }}</p></div>
          <button v-if="selectedEdge" class="button-secondary" data-return-lineage type="button" @click="returnToGraph">← 返回关系图</button>
        </header>
        <p v-if="!selectedEdge && selectedLineage.description" class="lineage-description">{{ selectedLineage.description }}</p>
        <LineageGraph v-show="!selectedEdge" :lineage="selectedLineage" :compounds="compounds" :structures="structureRecords" :visible="!selectedEdge" @select-edge="openEdge" />
        <div v-if="selectedEdge" class="edge-endpoint-pair">
          <EdgeCompoundCard :compound="compoundById.get(selectedEdge.parent_compound_id)" :compound-id="selectedEdge.parent_compound_id" :state="structureRecords[selectedEdge.parent_compound_id]" :workspace-id="workspace.id" :paper-id="workspace.bibliography.paper_id" :caption="selectedLineage.lineage_type === 'synthesis' ? '反应前体 / 路径起点' : selectedLineage.lineage_type === 'sar' || selectedEdge.relation_type === 'sar_baseline_comparison' ? '比较基线 / 设计起点' : '起点 / Parent'" @retry="retryStructure" />
          <EdgeCompoundCard :compound="compoundById.get(selectedEdge.child_compound_id)" :compound-id="selectedEdge.child_compound_id" :state="structureRecords[selectedEdge.child_compound_id]" :workspace-id="workspace.id" :paper-id="workspace.bibliography.paper_id" :caption="selectedLineage.lineage_type === 'synthesis' ? '产物 / 路径终点' : selectedLineage.lineage_type === 'sar' || selectedEdge.relation_type === 'sar_baseline_comparison' ? '被比较化合物' : '终点 / Child'" @retry="retryStructure" />
        </div>
        <section v-show="!selectedEdge" class="member-editor">
          <header class="compact-heading"><div><p class="eyebrow">MEMBERS</p><h4>Compound 角色</h4></div></header>
          <div class="member-list">
            <article v-for="member in selectedLineage.members" :key="member.id" class="member-row">
              <strong>{{ compoundById.get(member.compound_id)?.compound_label || member.compound_id }}</strong>
              <select :value="member.role" :disabled="readOnly || busy" @change="changeMemberRole(member, ($event.target as HTMLSelectElement).value as LineageMember['role'])"><option value="root">Root</option><option value="intermediate">Intermediate</option><option value="terminal">Terminal</option><option value="unspecified">Unspecified</option></select>
              <button class="button-quiet" type="button" :disabled="readOnly || busy" @click="removeMember(member)">删除 Member</button>
            </article>
          </div>
          <form class="inline-create-form" @submit.prevent="addMember">
            <label class="form-field">Compound<select v-model="newMemberCompoundId" :disabled="readOnly || busy"><option v-for="compound in availableCompounds" :key="compound.id" :value="compound.id">{{ compound.compound_label }}</option></select></label>
            <label class="form-field">角色<select v-model="newMemberRole" :disabled="readOnly || busy"><option value="root">Root</option><option value="intermediate">Intermediate</option><option value="terminal">Terminal</option><option value="unspecified">Unspecified</option></select></label>
            <button class="button-secondary" type="submit" :disabled="readOnly || busy || !newMemberCompoundId">添加 Member</button>
          </form>
        </section>
        <EdgeEditor v-if="displayedLineage" :lineage="displayedLineage" :focused-edge-id="selectedEdge?.id" :compounds="compounds" :read-only="readOnly" :busy="busy" @select="openEdge" @create="addEdge" @update="updateEdge" @delete="removeEdge">
          <template #evidence="{ edge }">
            <div class="edge-context-evidence" data-edge-context-evidence>
              <h5>关系证据</h5>
              <p v-if="evidenceLoading">正在读取证据…</p>
              <p v-else-if="evidenceError" role="alert">{{ evidenceError }}<button type="button" class="button-quiet" @click="loadEvidence">重试</button></p>
              <template v-else>
                <div v-for="link in linksForEdge(edge.id)" :key="link.id" data-edge-evidence-link>
                  <span class="status-chip">{{ link.role }}</span>
                  <EvidenceExcerpt v-if="evidenceById.get(link.evidence_id)" :evidence="evidenceById.get(link.evidence_id)!" :workspace="workspace" />
                  <p v-else>关联证据暂不可用，请核对。</p>
                </div>
                <p v-if="!linksForEdge(edge.id).length" class="evidence-empty">尚未关联证据。允许依据 AI 对结构或 SAR 的判断保留此关系，请核对修改摘要中的推断理由。</p>
              </template>
              <button v-if="!readOnly" class="button-quiet" data-manage-edge-evidence type="button" @click="managingEdgeId = managingEdgeId === edge.id ? undefined : edge.id">{{ managingEdgeId === edge.id ? '收起证据编辑' : '添加 / 编辑关系证据' }}</button>
              <EvidenceEditor v-if="managingEdgeId === edge.id" :key="edge.id" :workspace="{ ...workspace, version: localVersion }" :edge-id="edge.id" :read-only="readOnly" @mutated="evidenceMutation" @conflict="emit('conflict')" />
            </div>
          </template>
        </EdgeEditor>
      </div>
    </div>
    <details class="context-evidence-management" :open="showEvidenceLibrary" @toggle="showEvidenceLibrary = ($event.target as HTMLDetailsElement).open">
      <summary>全文证据库 / 未关联证据</summary>
      <EvidenceEditor v-if="showEvidenceLibrary" :workspace="{ ...workspace, version: localVersion }" :selected-entity-id="selectedEntityId" :read-only="readOnly" @mutated="evidenceMutation" @conflict="emit('conflict')" />
    </details>
  </section>
</template>

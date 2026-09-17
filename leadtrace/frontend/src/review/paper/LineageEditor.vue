<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

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
  listLineages,
  updateLineage,
  updateLineageEdge,
  updateLineageMember,
} from "../../v2/api";
import type { Compound, Lineage, LineageEdge, LineageMember, PaperWorkspace } from "../../v2/types";
import EdgeEditor from "./EdgeEditor.vue";
import LineageGraph from "./LineageGraph.vue";

const props = defineProps<{ workspace: PaperWorkspace; selectedEntityId?: string; readOnly?: boolean }>();
const emit = defineEmits<{ select: [entityId: string]; mutated: [workspaceVersion: number]; conflict: [] }>();
const auth = useAuthStore();
const compounds = ref<Compound[]>([]);
const lineages = ref<Lineage[]>([]);
const selectedLineageId = ref<string>();
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

const selectedLineage = computed(() => lineages.value.find((lineage) => lineage.id === selectedLineageId.value));
const compoundById = computed(() => new Map(compounds.value.map((compound) => [compound.id, compound])));
const availableCompounds = computed(() => {
  const members = new Set(selectedLineage.value?.members.map((member) => member.compound_id) ?? []);
  return compounds.value.filter((compound) => !members.has(compound.id));
});

watch(() => props.workspace.version, (version) => {
  if (version > localVersion.value) localVersion.value = version;
});
watch(() => props.workspace.id, () => { void load(); });
watch(() => props.selectedEntityId, selectAddressedRecord);
watch(availableCompounds, (items) => {
  if (!items.some((item) => item.id === newMemberCompoundId.value)) newMemberCompoundId.value = items[0]?.id ?? "";
}, { immediate: true });

function selectAddressedRecord(entityId?: string): void {
  if (!entityId) return;
  const lineage = lineages.value.find((item) => item.id === entityId
    || item.members.some((member) => member.id === entityId || member.compound_id === entityId)
    || item.edges.some((edge) => edge.id === entityId));
  if (lineage) selectedLineageId.value = lineage.id;
}

function selectLineage(lineage: Lineage): void {
  selectedLineageId.value = lineage.id;
  emit("select", lineage.id);
}

function startLineageEdit(lineage: Lineage): void {
  editingLineageId.value = lineage.id;
  editLineageLabel.value = lineage.lineage_label;
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
    localVersion.value = Math.max(compoundResult.workspace_version, lineageResult.workspace_version);
    selectAddressedRecord(props.selectedEntityId);
    if (!selectedLineageId.value || !lineages.value.some((item) => item.id === selectedLineageId.value)) {
      selectedLineageId.value = lineages.value[0]?.id;
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
      description: lineageDescription.value.trim() || null,
    }, auth.csrfToken);
    lineages.value = [...lineages.value, result.lineage];
    localVersion.value = result.workspace_version;
    lineageLabel.value = "";
    lineageDescription.value = "";
    showCreate.value = false;
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
    selectedLineageId.value = lineages.value[0]?.id;
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
      description: editLineageDescription.value.trim() || null,
    }, auth.csrfToken);
    lineages.value = lineages.value.map((item) => item.id === lineageId ? result.lineage : item);
    localVersion.value = result.workspace_version;
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
    <header class="section-heading"><div><p class="eyebrow">LINEAGES</p><h2>优化链</h2></div><button class="button-primary" data-add-lineage type="button" :disabled="readOnly || busy" @click="showCreate = !showCreate">添加 Lineage</button></header>
    <form v-if="showCreate" class="inline-create-form" @submit.prevent="create">
      <label class="form-field">Lineage label<input v-model="lineageLabel" data-lineage-label-input class="form-control" required maxlength="255"></label>
      <label class="form-field">描述<input v-model="lineageDescription" class="form-control" maxlength="10000"></label>
      <button class="button-primary" data-save-lineage type="button" :disabled="busy || !lineageLabel.trim()" @click="create">保存 Lineage</button>
    </form>
    <form v-if="editingLineageId" class="inline-create-form" @submit.prevent="saveLineageEdit">
      <label class="form-field">Lineage label<input v-model="editLineageLabel" data-edit-lineage-label class="form-control" required maxlength="255"></label>
      <label class="form-field">描述<input v-model="editLineageDescription" class="form-control" maxlength="10000"></label>
      <div class="editor-actions"><button class="button-primary" data-save-lineage-edit type="button" :disabled="busy || !editLineageLabel.trim()" @click="saveLineageEdit">保存修改</button><button class="button-quiet" type="button" :disabled="busy" @click="cancelLineageEdit">取消</button></div>
    </form>
    <p v-if="error" class="inline-feedback is-error" role="alert">{{ error }}</p>
    <p v-if="loading" class="workspace-empty-copy">正在读取 Lineage…</p>
    <p v-else-if="lineages.length === 0" class="workspace-empty-copy">当前尚无优化链。可按文章内容添加任意数量的 Lineage。</p>
    <div v-else class="lineage-editor-layout">
      <aside class="lineage-list-panel" aria-label="Lineage 列表">
        <article v-for="lineage in lineages" :key="lineage.id" data-lineage-card :data-lineage-id="lineage.id" :class="{ selected: lineage.id === selectedLineageId }">
          <button type="button" @click="selectLineage(lineage)"><strong>{{ lineage.lineage_label }}</strong><small>{{ lineage.members.length }} members · {{ lineage.edges.length }} edges</small></button>
          <div class="lineage-member-summary">
            <span v-for="member in lineage.members" :key="member.id" :data-member-role="member.role">{{ compoundById.get(member.compound_id)?.compound_label || "?" }} · {{ member.role }}</span>
          </div>
          <div v-if="!readOnly" class="editor-actions"><button class="button-quiet" data-edit-lineage type="button" :disabled="busy" @click="startLineageEdit(lineage)">编辑</button><button class="button-quiet" type="button" :disabled="busy" @click="removeLineage(lineage)">删除</button></div>
        </article>
      </aside>
      <div v-if="selectedLineage" class="lineage-detail-panel">
        <LineageGraph :lineage="selectedLineage" :compounds="compounds" />
        <section class="member-editor">
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
        <EdgeEditor :lineage="selectedLineage" :compounds="compounds" :read-only="readOnly" :busy="busy" @create="addEdge" @update="updateEdge" @delete="removeEdge" />
      </div>
    </div>
  </section>
</template>

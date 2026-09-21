<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import { ApiError } from "../../api/client";
import { useAuthStore } from "../../auth/store";
import { createCompound, deleteCompound, getCompoundStructure, listActivities, listCompounds, updateCompound } from "../../v2/api";
import type { Compound, PaperWorkspace } from "../../v2/types";
import ActivityEditor from "./ActivityEditor.vue";
import CompoundStructureEditor from "./CompoundStructureEditor.vue";

const props = defineProps<{
  workspace: PaperWorkspace;
  selectedCompoundId?: string;
  readOnly?: boolean;
}>();
const emit = defineEmits<{
  select: [compoundId: string];
  mutated: [workspaceVersion: number];
  conflict: [];
}>();
const auth = useAuthStore();
const compounds = ref<Compound[]>([]);
const selectedId = ref<string>();
const localVersion = ref(props.workspace.version);
const loading = ref(true);
const busy = ref(false);
const showCreate = ref(false);
const label = ref("");
const displayName = ref("");
const editingId = ref<string>();
const editLabel = ref("");
const editDisplayName = ref("");
const editDescription = ref("");
const error = ref("");
const nestedEntityOwner = new Map<string, string>();
const selected = computed(() => compounds.value.find((compound) => compound.id === selectedId.value));

watch(() => props.workspace.version, (version) => {
  if (version > localVersion.value) localVersion.value = version;
});
watch(() => props.selectedCompoundId, async (id) => {
  if (!id) return;
  const owner = await resolveOwner(id);
  if (props.selectedCompoundId === id && owner) selectedId.value = owner.id;
});
function selectActivity(entityId: string): void {
  if (selectedId.value) nestedEntityOwner.set(entityId, selectedId.value);
  emit("select", entityId);
}
async function resolveOwner(id: string): Promise<Compound | undefined> {
  const direct = compounds.value.find(item => item.id === id || item.id === nestedEntityOwner.get(id));
  if (direct) return direct;
  const activities = await Promise.allSettled(compounds.value.map(async item => ({ item, result: await listActivities(item.id) })));
  for (const result of activities) {
    if (result.status === "fulfilled" && result.value.result.items.some(a => a.id === id || a.evidence_id === id)) return result.value.item;
  }
  const structures = await Promise.allSettled(compounds.value.map(async item => ({ item, result: await getCompoundStructure(item.id) })));
  for (const result of structures) {
    if (result.status === "fulfilled" && result.value.result.structure?.id === id) return result.value.item;
  }
}
watch(() => props.workspace.id, () => { void load(); });

function select(compound: Compound): void {
  selectedId.value = compound.id;
  emit("select", compound.id);
}

function startEdit(compound: Compound): void {
  editingId.value = compound.id;
  editLabel.value = compound.compound_label;
  editDisplayName.value = compound.display_name ?? "";
  editDescription.value = compound.description ?? "";
}

function cancelEdit(): void {
  editingId.value = undefined;
  editLabel.value = "";
  editDisplayName.value = "";
  editDescription.value = "";
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const result = await listCompounds(props.workspace.id);
    compounds.value = result.items;
    localVersion.value = result.workspace_version;
    const requested = props.selectedCompoundId ? await resolveOwner(props.selectedCompoundId) : undefined;
    const next = requested ?? result.items[0];
    selectedId.value = next?.id;
    if (next && !props.selectedCompoundId) emit("select", next.id);
  } catch {
    error.value = "Compound 列表暂时无法读取。";
  } finally {
    loading.value = false;
  }
}

async function create(): Promise<void> {
  if (!label.value.trim() || props.readOnly || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await createCompound(props.workspace.id, {
      expected_workspace_version: localVersion.value,
      compound_label: label.value.trim(),
      display_name: displayName.value.trim() || null,
      description: null,
    }, auth.csrfToken);
    compounds.value = [...compounds.value, result.compound];
    localVersion.value = result.workspace_version;
    label.value = "";
    displayName.value = "";
    showCreate.value = false;
    select(result.compound);
    emit("mutated", result.workspace_version);
  } catch (reason) {
    if (reason instanceof ApiError && reason.code === "WORKSPACE_VERSION_CONFLICT") {
      emit("conflict");
      error.value = "Workspace 已更新，正在重新载入全部 Compound 数据。";
    } else {
      error.value = reason instanceof ApiError && reason.code === "COMPOUND_LABEL_CONFLICT"
        ? "该 Compound label 已存在。"
        : "Compound 未能创建，请重试。";
    }
  } finally {
    busy.value = false;
  }
}

async function saveCompound(): Promise<void> {
  const compoundId = editingId.value;
  if (!compoundId || !editLabel.value.trim() || props.readOnly || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await updateCompound(compoundId, {
      expected_workspace_version: localVersion.value,
      compound_label: editLabel.value.trim(),
      display_name: editDisplayName.value.trim() || null,
      description: editDescription.value.trim() || null,
    }, auth.csrfToken);
    compounds.value = compounds.value.map((item) => item.id === compoundId ? result.compound : item);
    localVersion.value = result.workspace_version;
    cancelEdit();
    emit("mutated", result.workspace_version);
  } catch (reason) {
    if (reason instanceof ApiError && reason.code === "WORKSPACE_VERSION_CONFLICT") {
      emit("conflict");
      error.value = "Workspace 已更新，正在重新载入全部 Compound 数据。";
    } else {
      error.value = reason instanceof ApiError && reason.code === "COMPOUND_LABEL_CONFLICT"
        ? "该 Compound label 已存在。"
        : "Compound 未能更新，请重试。";
    }
  } finally {
    busy.value = false;
  }
}

async function remove(compound: Compound): Promise<void> {
  if (props.readOnly || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await deleteCompound(compound.id, localVersion.value, auth.csrfToken);
    compounds.value = compounds.value.filter((item) => item.id !== compound.id);
    if (editingId.value === compound.id) cancelEdit();
    localVersion.value = result.workspace_version;
    selectedId.value = compounds.value[0]?.id;
    if (selectedId.value) emit("select", selectedId.value);
    emit("mutated", result.workspace_version);
  } catch (reason) {
    if (reason instanceof ApiError && reason.code === "WORKSPACE_VERSION_CONFLICT") {
      emit("conflict");
      error.value = "Workspace 已更新，正在重新载入全部 Compound 数据。";
    } else {
      error.value = reason instanceof ApiError && reason.code === "COMPOUND_REFERENCED"
        ? "该 Compound 已被 Lineage 或 Activity 引用，不能删除。"
        : "Compound 未能删除，请重试。";
    }
  } finally {
    busy.value = false;
  }
}

function nestedMutation(version: number): void {
  localVersion.value = version;
  emit("mutated", version);
}

function nestedConflict(): void {
  emit("conflict");
}

onMounted(load);
</script>

<template>
  <section class="compound-workspace" data-compound-list>
    <header class="section-heading">
      <div><p class="eyebrow">COMPOUNDS & STRUCTURES</p><h2>化合物与结构</h2></div>
      <button class="button-primary" data-add-compound type="button" :disabled="readOnly || busy" @click="showCreate = !showCreate">添加 Compound</button>
    </header>
    <form v-if="showCreate" class="inline-create-form" @submit.prevent="create">
      <label class="form-field">Compound label<input v-model="label" class="form-control" required maxlength="255"></label>
      <label class="form-field">显示名称<input v-model="displayName" class="form-control" maxlength="512"></label>
      <button class="button-primary" type="submit" :disabled="busy || !label.trim()">保存 Compound</button>
    </form>
    <form v-if="editingId" class="inline-create-form compound-edit-form" @submit.prevent="saveCompound">
      <label class="form-field">Compound label<input v-model="editLabel" data-edit-compound-label class="form-control" required maxlength="255"></label>
      <label class="form-field">显示名称<input v-model="editDisplayName" data-edit-compound-name class="form-control" maxlength="512"></label>
      <label class="form-field">描述<textarea v-model="editDescription" data-edit-compound-description class="form-control" rows="2" maxlength="10000"></textarea></label>
      <div class="editor-actions">
        <button class="button-primary" data-save-compound type="button" :disabled="busy || !editLabel.trim()" @click="saveCompound">保存修改</button>
        <button class="button-quiet" type="button" :disabled="busy" @click="cancelEdit">取消</button>
      </div>
    </form>
    <p v-if="error" class="inline-feedback is-error" role="alert">{{ error }}</p>
    <p v-if="loading" class="workspace-empty-copy">正在读取 Compound…</p>
    <p v-else-if="compounds.length === 0" class="workspace-empty-copy">当前尚无条目。可直接人工新增 Compound，并为每个 Compound 维护一个 Structure。</p>
    <div v-else class="compound-editor-layout">
      <aside class="compound-list-panel" aria-label="Compound 列表" tabindex="0">
        <article v-for="compound in compounds" :key="compound.id" data-compound-row :data-compound-id="compound.id" :class="{ selected: compound.id === selectedId }">
          <button type="button" @click="select(compound)"><code>{{ compound.compound_label }}</code><span>{{ compound.display_name || "未命名" }}</span></button>
          <button v-if="!readOnly" class="button-quiet" data-edit-compound type="button" :disabled="busy" @click="startEdit(compound)">编辑</button>
          <button v-if="!readOnly" class="button-quiet" type="button" :disabled="busy" @click="remove(compound)">删除</button>
        </article>
      </aside>
      <div v-if="selected" :key="selected.id" class="compound-detail-panel">
      <CompoundStructureEditor
        :key="selected.id"
        :compound="selected"
        :workspace-version="localVersion"
        :source="workspace.source"
        :read-only="readOnly"
        @mutated="nestedMutation"
        @conflict="nestedConflict"
      />
      <ActivityEditor :workspace="{ ...workspace, version: localVersion }" :compound="selected" :selected-entity-id="selectedCompoundId" :read-only="readOnly" @select="selectActivity" @mutated="nestedMutation" @conflict="nestedConflict" />
      </div>
    </div>
  </section>
</template>

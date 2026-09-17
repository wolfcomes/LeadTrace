<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import { ApiError } from "../../api/client";
import { useAuthStore } from "../../auth/store";
import { getCompoundStructure, putCompoundStructure } from "../../v2/api";
import type { Compound, PaperWorkspace, Structure } from "../../v2/types";
import KetcherEditor from "./KetcherEditor.vue";
import StructureSourceImages from "./StructureSourceImages.vue";

const props = defineProps<{
  compound: Compound;
  workspaceVersion: number;
  source: PaperWorkspace["source"];
  readOnly?: boolean;
}>();
const emit = defineEmits<{ mutated: [workspaceVersion: number]; conflict: [] }>();
const auth = useAuthStore();
const structure = ref<Structure | null>(null);
const smiles = ref("");
const molfile = ref("");
const loadedSmiles = ref("");
const loadedMolfile = ref("");
const localVersion = ref(props.workspaceVersion);
const showKetcher = ref(false);
const ketcherOutputReady = ref(false);
const loading = ref(true);
const saving = ref(false);
const error = ref("");

watch(() => props.workspaceVersion, (version) => {
  if (version > localVersion.value) localVersion.value = version;
});
watch(() => props.compound.id, () => { void load(); });

const dirty = computed(() => smiles.value !== loadedSmiles.value || molfile.value !== loadedMolfile.value);
const canConfirm = computed(() => Boolean(
  structure.value
  && (structure.value.canonical_smiles || structure.value.inchi)
  && !dirty.value
  && !props.readOnly
  && !saving.value,
));
const inputMethodLabel = computed(() => ({
  ai_prefill: "AI 预填",
  manual_smiles: "人工 SMILES",
  structure_editor: "Ketcher",
}[structure.value?.input_method ?? "manual_smiles"]));
const statusLabel = computed(() => ({
  draft: "Draft",
  reviewer_confirmed: "Reviewer 已确认",
  unresolved: "无法解析",
  not_reported: "文章未报告",
}[structure.value?.status ?? "draft"]));

function apply(result: Structure | null): void {
  structure.value = result;
  smiles.value = result?.smiles ?? "";
  molfile.value = result?.molfile ?? "";
  loadedSmiles.value = smiles.value;
  loadedMolfile.value = molfile.value;
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const result = await getCompoundStructure(props.compound.id);
    localVersion.value = result.workspace_version;
    apply(result.structure);
  } catch {
    error.value = "Structure 暂时无法读取。";
  } finally {
    loading.value = false;
  }
}

async function save(inputMethod: "manual_smiles" | "structure_editor", status: "draft" | "reviewer_confirmed" = "draft"): Promise<void> {
  if (props.readOnly || saving.value) return;
  saving.value = true;
  error.value = "";
  try {
    const result = await putCompoundStructure(props.compound.id, {
      expected_workspace_version: localVersion.value,
      status,
      input_method: inputMethod,
      smiles: inputMethod === "manual_smiles" ? smiles.value || null : null,
      molfile: inputMethod === "structure_editor" ? molfile.value || null : null,
    }, auth.csrfToken);
    localVersion.value = result.workspace_version;
    apply(result.structure);
    emit("mutated", result.workspace_version);
  } catch (reason) {
    if (reason instanceof ApiError && reason.code === "STRUCTURE_INVALID") {
      error.value = "该结构无法被 RDKit 确认为有效分子；可继续保存为 Draft 后修订。";
    } else if (reason instanceof ApiError && reason.code === "WORKSPACE_VERSION_CONFLICT") {
      emit("conflict");
      error.value = "Workspace 已更新，正在重新载入全部 Compound 数据。";
    } else {
      error.value = "Structure 未能保存，请重试。";
    }
  } finally {
    saving.value = false;
  }
}

async function markNoStructure(status: "unresolved" | "not_reported"): Promise<void> {
  if (props.readOnly || saving.value) return;
  saving.value = true;
  error.value = "";
  try {
    const result = await putCompoundStructure(props.compound.id, {
      expected_workspace_version: localVersion.value,
      status,
      input_method: "manual_smiles",
      smiles: null,
      molfile: null,
    }, auth.csrfToken);
    localVersion.value = result.workspace_version;
    apply(result.structure);
    emit("mutated", result.workspace_version);
  } catch (reason) {
    if (reason instanceof ApiError && reason.code === "WORKSPACE_VERSION_CONFLICT") {
      emit("conflict");
      error.value = "Workspace 已更新，正在重新载入全部 Compound 数据。";
    } else {
      error.value = "Structure 状态未能保存，请重试。";
    }
  } finally {
    saving.value = false;
  }
}

function handleNestedMutation(version: number): void {
  localVersion.value = version;
  emit("mutated", version);
}

function handleNestedConflict(): void {
  emit("conflict");
}

function toggleKetcher(): void {
  if (!showKetcher.value && !molfile.value) {
    molfile.value = structure.value?.molfile ?? structure.value?.smiles ?? "";
  }
  showKetcher.value = !showKetcher.value;
  ketcherOutputReady.value = false;
}

function handleKetcherOutput(value: string): void {
  molfile.value = value;
  ketcherOutputReady.value = Boolean(value.trim());
}

onMounted(load);
</script>

<template>
  <section class="compound-structure-editor" data-structure-editor>
    <header class="section-heading compact-heading">
      <div><p class="eyebrow">SINGLE CURRENT STRUCTURE</p><h3>{{ compound.compound_label }} · {{ compound.display_name || "未命名 Compound" }}</h3></div>
      <div class="structure-meta"><span data-structure-status class="status-chip">{{ statusLabel }}</span><small data-structure-input-method>{{ inputMethodLabel }}</small></div>
    </header>
    <p v-if="error" class="inline-feedback is-error" role="alert">{{ error }}</p>
    <p v-if="loading" class="workspace-empty-copy">正在读取 Structure…</p>
    <template v-else>
      <div class="structure-form-grid">
        <label class="form-field">SMILES<textarea v-model="smiles" data-smiles-input class="form-control" rows="4" :disabled="readOnly || saving" placeholder="输入 SMILES"></textarea></label>
        <div class="structure-identifiers">
          <dl><div><dt>Canonical SMILES</dt><dd><code>{{ structure?.canonical_smiles || "待 RDKit 解析" }}</code></dd></div><div><dt>InChIKey</dt><dd><code>{{ structure?.inchikey || "—" }}</code></dd></div></dl>
          <p data-structure-guidance>{{ canConfirm ? "RDKit 已解析，可确认当前 Structure。" : "先保存 Draft；RDKit 成功解析且无未保存修改后才能确认。" }}</p>
        </div>
      </div>
      <div class="editor-actions structure-actions">
        <button class="button-primary" data-save-structure type="button" :disabled="readOnly || saving || !smiles.trim()" @click="save('manual_smiles')">保存 SMILES Draft</button>
        <button class="button-secondary" data-confirm-structure type="button" :disabled="!canConfirm" @click="save(structure?.input_method === 'structure_editor' ? 'structure_editor' : 'manual_smiles', 'reviewer_confirmed')">确认 Structure</button>
        <button class="button-secondary" data-open-ketcher type="button" :disabled="readOnly || saving" @click="toggleKetcher">{{ showKetcher ? "关闭 Ketcher" : "用 Ketcher 编辑" }}</button>
        <button class="button-quiet" data-mark-structure="unresolved" type="button" :disabled="readOnly || saving" @click="markNoStructure('unresolved')">标记无法解析</button>
        <button class="button-quiet" data-mark-structure="not_reported" type="button" :disabled="readOnly || saving" @click="markNoStructure('not_reported')">文章未报告结构</button>
      </div>
      <section v-if="showKetcher" class="ketcher-panel">
        <KetcherEditor :model-value="molfile" :disabled="readOnly" @update:model-value="handleKetcherOutput" @error="error = $event" />
        <button class="button-primary" data-save-ketcher type="button" :disabled="readOnly || saving || !ketcherOutputReady" @click="save('structure_editor')">保存 Ketcher Draft</button>
      </section>
      <StructureSourceImages
        :compound-id="compound.id"
        :paper-id="compound.paper_id"
        :workspace-version="localVersion"
        :source="source"
        :structure="structure"
        :read-only="readOnly"
        @mutated="handleNestedMutation"
        @conflict="handleNestedConflict"
      />
    </template>
  </section>
</template>

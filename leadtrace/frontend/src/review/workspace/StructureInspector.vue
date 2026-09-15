<script setup lang="ts">
import { computed, ref, watch } from "vue";

import StructureEditor from "../../structures/StructureEditor.vue";
import type {
  ExperimentalMaterialValue,
  SourceComparisonValue,
  StructureStateValue,
  StructureValidationInput,
  StructureValidationResult,
} from "../api";
import type { WorkspaceStructure } from "./types";

export interface StructureEditorValue {
  smiles: string | null;
  source: string;
  reason: string;
  structureState: StructureStateValue;
  selectedComponentSmiles: string | null;
  experimentalMaterial: ExperimentalMaterialValue;
  sourceComparison: SourceComparisonValue;
  sourceVerified: boolean;
  humanConfirmed: boolean;
}

const props = defineProps<{
  structure?: WorkspaceStructure;
  compoundId?: string;
  editable: boolean;
  busy?: boolean;
  validation: StructureValidationResult | null;
  drawingUrl: string | null;
}>();

const emit = defineEmits<{
  validate: [payload: StructureValidationInput];
  draw: [smiles: string];
  save: [payload: StructureEditorValue & { compound_id: string; structure_key: string }];
}>();

function text(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function boolean(value: unknown): boolean {
  return value === true;
}

function sourceComparison(value: unknown): SourceComparisonValue {
  return value === "match" || value === "mismatch" ? value : "not_compared";
}

function experimentalMaterial(value: unknown): ExperimentalMaterialValue {
  return value === "non_unique_stereochemistry" || value === "multicomponent" || value === "constitution_only"
    ? value
    : "unique";
}

function state(value: unknown): StructureStateValue {
  const allowed: StructureStateValue[] = [
    "proposal", "parseable_candidate", "source_bound_candidate", "structure_confirmed",
    "constitution_confirmed", "non_unique_stereochemistry", "multicomponent_unresolved",
    "source_structure_mismatch", "rejected",
  ];
  return allowed.includes(value as StructureStateValue) ? value as StructureStateValue : "proposal";
}

function initialValue(): StructureEditorValue {
  const snapshot = props.structure?.snapshot ?? {};
  return {
    smiles: text(snapshot.input_smiles ?? props.structure?.canonical_smiles) || null,
    source: text(snapshot.source),
    reason: "",
    structureState: state(snapshot.structure_state ?? props.structure?.state),
    selectedComponentSmiles: text(snapshot.selected_component_smiles) || null,
    experimentalMaterial: experimentalMaterial(snapshot.experimental_material),
    sourceComparison: sourceComparison(snapshot.source_comparison),
    sourceVerified: boolean(snapshot.source_verified),
    humanConfirmed: boolean(snapshot.human_confirmed),
  };
}

const model = ref<StructureEditorValue>(initialValue());
const compoundId = ref(props.structure?.compound_id ?? props.compoundId ?? "");
const structureKey = ref(props.structure?.structure_key ?? "");
const drawingFailed = ref(false);

watch(() => props.structure, () => {
  model.value = initialValue();
  compoundId.value = props.structure?.compound_id ?? props.compoundId ?? "";
  structureKey.value = props.structure?.structure_key ?? "";
  drawingFailed.value = false;
}, { deep: true });

watch(() => props.drawingUrl, () => { drawingFailed.value = false; });

const validationShape = computed(() => props.validation ? {
  parseable: props.validation.parseable,
  messages: props.validation.messages,
  componentCount: props.validation.componentCount,
  eligibleStates: props.validation.eligibleStates,
} : null);

function validationInput(smiles = model.value.smiles ?? ""): StructureValidationInput {
  return {
    smiles,
    selected_component_smiles: model.value.selectedComponentSmiles,
    experimental_material: model.value.experimentalMaterial,
    source_comparison: model.value.sourceComparison,
    source_verified: model.value.sourceVerified,
    human_confirmed: model.value.humanConfirmed,
  };
}

function save(value: {
  smiles: string | null;
  source: string;
  reason: string;
  structureState: string;
  selectedComponentSmiles?: string | null;
  experimentalMaterial?: ExperimentalMaterialValue;
  sourceComparison?: SourceComparisonValue;
  sourceVerified?: boolean;
  humanConfirmed?: boolean;
}): void {
  if (!props.editable || props.busy || !compoundId.value.trim() || !structureKey.value.trim()) return;
  emit("save", {
    smiles: value.smiles,
    source: value.source,
    reason: value.reason,
    structureState: state(value.structureState),
    selectedComponentSmiles: value.selectedComponentSmiles ?? null,
    experimentalMaterial: value.experimentalMaterial ?? "unique",
    sourceComparison: value.sourceComparison ?? "not_compared",
    sourceVerified: value.sourceVerified ?? false,
    humanConfirmed: value.humanConfirmed ?? false,
    compound_id: compoundId.value.trim(),
    structure_key: structureKey.value.trim(),
  });
}
</script>

<template>
  <section class="structure-inspector" data-structure-inspector aria-label="Structure 专用编辑器">
    <header class="structure-identity">
      <div><p class="eyebrow">STRUCTURE</p><h2>{{ structure?.structure_key ?? "新建 Structure" }}</h2></div>
      <span v-if="structure?.state" class="status-chip" :data-state="structure.state">{{ structure.state }}</span>
    </header>

    <div class="structure-reference-grid">
      <label class="form-field">Compound ID<input v-model="compoundId" class="form-control" name="structure-compound-id" :readonly="Boolean(structure)" :disabled="!editable || busy"></label>
      <label class="form-field">Structure key<input v-model="structureKey" class="form-control" name="structure-key" :readonly="Boolean(structure)" :disabled="!editable || busy"></label>
    </div>

    <div class="structure-drawing evidence-preview-frame" data-structure-drawing>
      <img v-if="drawingUrl && !drawingFailed" :src="drawingUrl" :alt="`${structureKey || '当前结构'} 的 RDKit 图`" @error="drawingFailed = true">
      <p v-else data-drawing-fallback>尚未生成 RDKit 图；SMILES 仍可继续校验和保存。</p>
      <button
        class="button-secondary"
        data-draw-structure
        type="button"
        :disabled="!editable || busy || !model.smiles?.trim()"
        @click="emit('draw', model.smiles?.trim() ?? '')"
      >生成 RDKit 图</button>
    </div>

    <StructureEditor
      v-model="model"
      :validation="validationShape"
      :editable="editable && !busy"
      @validate="emit('validate', validationInput($event))"
      @save="save"
    />
  </section>
</template>

<style scoped>
.structure-inspector { display: grid; gap: 13px; padding-top: 14px; border-top: 1px solid var(--line); }
.structure-identity { display: flex; align-items: flex-start; justify-content: space-between; gap: 9px; }
.structure-identity h2 { margin: 0; }
.structure-reference-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.structure-drawing { min-height: 230px; }
.structure-inspector :deep(.structure-editor) { margin: 0; border: 0; box-shadow: none; }
</style>

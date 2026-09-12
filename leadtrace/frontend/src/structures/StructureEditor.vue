<script setup lang="ts">
import { computed, reactive, watch } from "vue";

type StructureDraft = {
  smiles: string | null;
  source: string;
  reason: string;
  structureState: string;
  selectedComponentSmiles?: string | null;
};

const props = defineProps<{
  modelValue: StructureDraft;
  validation?: { parseable: boolean; messages: string[]; componentCount: number } | null;
  editable?: boolean;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: StructureDraft];
  validate: [smiles: string];
  save: [value: StructureDraft];
}>();

const draft = reactive<StructureDraft>({ ...props.modelValue });
watch(() => props.modelValue, (value) => Object.assign(draft, value), { deep: true });
watch(draft, () => emit("update:modelValue", { ...draft }), { deep: true });

const canSave = computed(() => Boolean(
  props.editable
  && draft.source.trim()
  && draft.reason.trim()
  && (draft.smiles?.trim() || draft.structureState === "non_unique_stereochemistry"
    || draft.structureState === "multicomponent_unresolved"
    || draft.structureState === "rejected"),
));

const states = [
  ["proposal", "候选结构"],
  ["parseable_candidate", "RDKit 可解析"],
  ["source_bound_candidate", "已绑定来源"],
  ["structure_confirmed", "结构已确认"],
  ["constitution_confirmed", "仅构造确认"],
  ["non_unique_stereochemistry", "非唯一立体化学"],
  ["multicomponent_unresolved", "多组分未解析"],
  ["source_structure_mismatch", "来源与结构不一致"],
  ["rejected", "已拒绝"],
] as const;
</script>

<template>
  <form class="structure-editor" aria-label="结构核查" @submit.prevent="emit('save', { ...draft })">
    <header>
      <div>
        <span>STRUCTURE REVIEW</span>
        <h2>结构核查</h2>
      </div>
      <strong
        data-parse-status
        :class="props.validation?.parseable ? 'valid' : 'pending'"
      >{{ props.validation?.parseable ? "RDKit 可解析" : "待解析" }}</strong>
    </header>

    <label>
      SMILES
      <textarea
        v-model="draft.smiles"
        name="smiles"
        rows="4"
        :disabled="!props.editable"
        @blur="emit('validate', draft.smiles?.trim() ?? '')"
      />
    </label>

    <div class="form-grid">
      <label>
        科学状态
        <select v-model="draft.structureState" :disabled="!props.editable">
          <option v-for="[value, label] in states" :key="value" :value="value">{{ label }}</option>
        </select>
      </label>
      <label v-if="(props.validation?.componentCount ?? 0) > 1">
        选定组分
        <input v-model="draft.selectedComponentSmiles" name="selected-component" :disabled="!props.editable">
      </label>
    </div>

    <label>
      来源
      <input v-model="draft.source" name="source" :disabled="!props.editable">
    </label>
    <label>
      修改理由
      <textarea v-model="draft.reason" name="reason" rows="2" :disabled="!props.editable" />
    </label>

    <footer>
      <span v-if="props.validation?.messages.length">{{ props.validation.messages.join(" · ") }}</span>
      <button type="submit" :disabled="!canSave">保存草稿</button>
    </footer>
  </form>
</template>

<style scoped>
.structure-editor { display: grid; gap: 14px; padding: 18px; border: 1px solid #d8dee4; background: #fff; }
header, footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
header span { color: #68737e; font-size: .68rem; font-weight: 750; letter-spacing: .08em; }
h2 { margin: 3px 0 0; color: #1f2d38; font-size: 1rem; }
header strong { border-left: 3px solid; padding-left: 8px; font-size: .76rem; }
header strong.valid { border-color: #17835c; color: #126447; }
header strong.pending { border-color: #b78024; color: #785619; }
label { display: grid; gap: 6px; color: #46525d; font-size: .78rem; font-weight: 650; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
input, select, textarea { width: 100%; box-sizing: border-box; border: 1px solid #cbd3da; border-radius: 4px; padding: 8px 10px; color: #1f2d38; background: #fff; font: inherit; resize: vertical; }
footer span { color: #8a5b13; font-size: .73rem; }
button { min-height: 36px; border: 1px solid #174f66; border-radius: 4px; padding: 7px 13px; color: #fff; background: #174f66; font: inherit; font-weight: 700; }
button:disabled { border-color: #b7c0c7; background: #b7c0c7; cursor: not-allowed; }
@media (max-width: 620px) { .form-grid { grid-template-columns: 1fr; } }
</style>

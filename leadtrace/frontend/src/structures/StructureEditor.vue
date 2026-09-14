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
  <form class="structure-editor editor-form panel" aria-label="结构核查" @submit.prevent="emit('save', { ...draft })">
    <header class="editor-heading editor-heading--split">
      <div>
        <span>STRUCTURE REVIEW</span>
        <h2>结构核查</h2>
      </div>
      <strong
        data-parse-status
        :class="['status-chip', props.validation?.parseable ? 'is-ok' : 'is-pending']"
      >{{ props.validation?.parseable ? "RDKit 可解析" : "待解析" }}</strong>
    </header>

    <label class="form-field">
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
      <label class="form-field">
        科学状态
        <select v-model="draft.structureState" :disabled="!props.editable">
          <option v-for="[value, label] in states" :key="value" :value="value">{{ label }}</option>
        </select>
      </label>
      <label v-if="(props.validation?.componentCount ?? 0) > 1" class="form-field">
        选定组分
        <input v-model="draft.selectedComponentSmiles" name="selected-component" :disabled="!props.editable">
      </label>
    </div>

    <label class="form-field">
      来源
      <input v-model="draft.source" name="source" :disabled="!props.editable">
    </label>
    <label class="form-field">
      修改理由
      <textarea v-model="draft.reason" name="reason" rows="2" :disabled="!props.editable" />
    </label>

    <footer class="editor-actions">
      <span v-if="props.validation?.messages.length">{{ props.validation.messages.join(" · ") }}</span>
      <button class="button-primary" type="submit" :disabled="!canSave">保存草稿</button>
    </footer>
  </form>
</template>

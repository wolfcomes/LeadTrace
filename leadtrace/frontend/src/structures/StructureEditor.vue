<script setup lang="ts">
import { computed, reactive, watch } from "vue";

type StructureDraft = {
  smiles: string | null;
  source: string;
  reason: string;
  structureState: string;
  selectedComponentSmiles?: string | null;
  experimentalMaterial?: "unique" | "non_unique_stereochemistry" | "multicomponent" | "constitution_only";
  sourceComparison?: "match" | "mismatch" | "not_compared";
  sourceVerified?: boolean;
  humanConfirmed?: boolean;
};

const props = defineProps<{
  modelValue: StructureDraft;
  validation?: { parseable: boolean; messages: string[]; componentCount: number; eligibleStates?: string[] } | null;
  editable?: boolean;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: StructureDraft];
  validate: [smiles: string];
  save: [value: StructureDraft];
}>();

const draft = reactive<StructureDraft>({
  experimentalMaterial: "unique",
  sourceComparison: "not_compared",
  sourceVerified: false,
  humanConfirmed: false,
  ...props.modelValue,
});
watch(() => props.modelValue, (value) => Object.assign(draft, {
  experimentalMaterial: "unique",
  sourceComparison: "not_compared",
  sourceVerified: false,
  humanConfirmed: false,
  ...value,
}), { deep: true });
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
      <label class="form-field">
        实验材料
        <select v-model="draft.experimentalMaterial" name="experimental-material" :disabled="!props.editable">
          <option value="unique">唯一结构</option>
          <option value="non_unique_stereochemistry">非唯一立体化学</option>
          <option value="multicomponent">多组分</option>
          <option value="constitution_only">仅构造</option>
        </select>
      </label>
      <label class="form-field">
        来源对照
        <select v-model="draft.sourceComparison" name="source-comparison" :disabled="!props.editable">
          <option value="not_compared">尚未对照</option>
          <option value="match">与来源一致</option>
          <option value="mismatch">与来源不一致</option>
        </select>
      </label>
    </div>

    <div class="confirmation-grid">
      <label><input v-model="draft.sourceVerified" name="source-verified" type="checkbox" :disabled="!props.editable"> 已核对来源位置</label>
      <label><input v-model="draft.humanConfirmed" name="human-confirmed" type="checkbox" :disabled="!props.editable"> 人工确认结构解释</label>
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
      <span v-if="props.validation?.messages.length" data-validation-messages>{{ props.validation.messages.join(" · ") }}</span>
      <button class="button-primary" type="submit" :disabled="!canSave">保存草稿</button>
    </footer>
  </form>
</template>

<style scoped>
.confirmation-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; color: var(--ink-soft); font-size: .75rem; }
</style>

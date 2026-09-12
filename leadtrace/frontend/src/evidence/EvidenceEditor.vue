<script setup lang="ts">
import { computed, reactive, watch } from "vue";

type EvidenceDraft = {
  evidenceKey: string;
  originalText: string;
  sourceLocator: string;
  compoundIds: string[];
  reason: string;
};

const props = defineProps<{ modelValue: EvidenceDraft; editable?: boolean }>();
const emit = defineEmits<{ "update:modelValue": [value: EvidenceDraft]; save: [value: EvidenceDraft] }>();
const draft = reactive<EvidenceDraft>({ ...props.modelValue, compoundIds: [...props.modelValue.compoundIds] });
watch(() => props.modelValue, (value) => Object.assign(draft, { ...value, compoundIds: [...value.compoundIds] }), { deep: true });
watch(draft, () => emit("update:modelValue", { ...draft, compoundIds: [...draft.compoundIds] }), { deep: true });
const canSave = computed(() => Boolean(props.editable && draft.originalText.trim() && draft.sourceLocator.trim() && draft.reason.trim()));
</script>

<template>
  <form class="editor" aria-label="证据核查" @submit.prevent="emit('save', { ...draft, compoundIds: [...draft.compoundIds] })">
    <header><span>EVIDENCE REVIEW</span><h2>证据核查</h2></header>
    <label>证据编号<input v-model="draft.evidenceKey" name="evidence-key" :disabled="!props.editable"></label>
    <label>原始证据文本<textarea v-model="draft.originalText" name="original-text" rows="5" :disabled="!props.editable"></textarea></label>
    <label>来源定位<input v-model="draft.sourceLocator" name="source-locator" :disabled="!props.editable"></label>
    <label>修改理由<input v-model="draft.reason" name="reason" :disabled="!props.editable"></label>
    <footer><small>绑定化合物：{{ draft.compoundIds.length }}</small><button type="submit" :disabled="!canSave">保存草稿</button></footer>
  </form>
</template>

<style scoped>
.editor { display: grid; gap: 13px; padding: 18px; border: 1px solid #d8dee4; background: #fff; }
header span { color: #68737e; font-size: .68rem; font-weight: 750; letter-spacing: .08em; } h2 { margin: 3px 0 0; font-size: 1rem; color: #1f2d38; }
label { display: grid; gap: 6px; color: #46525d; font-size: .78rem; font-weight: 650; } input, textarea { box-sizing: border-box; width: 100%; border: 1px solid #cbd3da; border-radius: 4px; padding: 8px 10px; font: inherit; resize: vertical; }
footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; } small { color: #6f7b85; } button { min-height: 36px; border: 1px solid #174f66; border-radius: 4px; padding: 7px 13px; color: #fff; background: #174f66; font: inherit; font-weight: 700; } button:disabled { border-color: #b7c0c7; background: #b7c0c7; }
</style>

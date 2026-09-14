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
  <form class="editor editor-form panel" aria-label="证据核查" @submit.prevent="emit('save', { ...draft, compoundIds: [...draft.compoundIds] })">
    <header class="editor-heading"><span>EVIDENCE REVIEW</span><h2>证据核查</h2></header>
    <label class="form-field">证据编号<input v-model="draft.evidenceKey" name="evidence-key" :disabled="!props.editable"></label>
    <label class="form-field">原始证据文本<textarea v-model="draft.originalText" name="original-text" rows="5" :disabled="!props.editable"></textarea></label>
    <label class="form-field">来源定位<input v-model="draft.sourceLocator" name="source-locator" :disabled="!props.editable"></label>
    <label class="form-field">修改理由<input v-model="draft.reason" name="reason" :disabled="!props.editable"></label>
    <footer class="editor-actions"><small>绑定化合物：{{ draft.compoundIds.length }}</small><button class="button-primary" type="submit" :disabled="!canSave">保存草稿</button></footer>
  </form>
</template>

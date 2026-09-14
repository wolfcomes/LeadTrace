<script setup lang="ts">
import { computed, reactive, watch } from "vue";

type CompoundDraft = { localIdentity: string; displayLabel: string; reason: string };
const props = defineProps<{ modelValue: CompoundDraft; editable?: boolean }>();
const emit = defineEmits<{ "update:modelValue": [value: CompoundDraft]; save: [value: CompoundDraft] }>();
const draft = reactive<CompoundDraft>({ ...props.modelValue });
watch(() => props.modelValue, (value) => Object.assign(draft, value), { deep: true });
watch(draft, () => emit("update:modelValue", { ...draft }), { deep: true });
const canSave = computed(() => Boolean(props.editable && draft.localIdentity.trim() && draft.displayLabel.trim() && draft.reason.trim()));
</script>

<template>
  <form class="editor editor-form panel" aria-label="化合物核查" @submit.prevent="emit('save', { ...draft })">
    <header class="editor-heading"><span>COMPOUND REVIEW</span><h2>Paper-local 化合物</h2></header>
    <label class="form-field">本地编号<input v-model="draft.localIdentity" name="local-identity" :disabled="!props.editable"></label>
    <label class="form-field">显示标签<input v-model="draft.displayLabel" name="display-label" :disabled="!props.editable"></label>
    <label class="form-field">创建或修改理由<textarea v-model="draft.reason" name="reason" rows="3" :disabled="!props.editable"></textarea></label>
    <button class="button-primary" type="submit" :disabled="!canSave">保存草稿</button>
  </form>
</template>

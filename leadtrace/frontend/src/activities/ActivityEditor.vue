<script setup lang="ts">
import { reactive, watch } from "vue";

type ActivityDraft = { activityKey: string; assay: string; metric: string; value: string; unit: string; qualifier: string; evidenceText: string; reason: string };
const props = defineProps<{ modelValue: ActivityDraft; editable?: boolean }>();
const emit = defineEmits<{ "update:modelValue": [value: ActivityDraft]; save: [value: ActivityDraft] }>();
const draft = reactive<ActivityDraft>({ ...props.modelValue });
watch(() => props.modelValue, (value) => Object.assign(draft, value), { deep: true });
watch(draft, () => emit("update:modelValue", { ...draft }), { deep: true });
const fields: Array<[keyof ActivityDraft, string, string]> = [
  ["assay", "实验体系", "text"], ["metric", "指标", "text"], ["value", "数值", "text"], ["unit", "单位", "text"], ["qualifier", "限定符", "text"],
];
</script>

<template>
  <form class="editor editor-form panel" aria-label="活性核查" @submit.prevent="emit('save', { ...draft })">
    <header class="editor-heading"><span>ACTIVITY REVIEW</span><h2>活性核查</h2></header>
    <label v-for="[key, label, type] in fields" :key="key" class="form-field" data-activity-field>{{ label }}<input v-model="draft[key]" :name="key" :type="type" :disabled="!props.editable"></label>
    <label class="form-field">原始证据文本<textarea v-model="draft.evidenceText" name="evidence-text" rows="3" :disabled="!props.editable"></textarea></label>
    <label class="form-field">修改理由<input v-model="draft.reason" name="reason" :disabled="!props.editable"></label>
    <button class="button-primary" type="submit" :disabled="!props.editable || !draft.reason.trim()">保存草稿</button>
  </form>
</template>

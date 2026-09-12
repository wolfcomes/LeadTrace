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
  <form class="editor" aria-label="活性核查" @submit.prevent="emit('save', { ...draft })">
    <header><span>ACTIVITY REVIEW</span><h2>活性核查</h2></header>
    <label v-for="[key, label, type] in fields" :key="key" data-activity-field>{{ label }}<input v-model="draft[key]" :name="key" :type="type" :disabled="!props.editable"></label>
    <label>原始证据文本<textarea v-model="draft.evidenceText" name="evidence-text" rows="3" :disabled="!props.editable"></textarea></label>
    <label>修改理由<input v-model="draft.reason" name="reason" :disabled="!props.editable"></label>
    <button type="submit" :disabled="!props.editable || !draft.reason.trim()">保存草稿</button>
  </form>
</template>

<style scoped>
.editor { display: grid; gap: 12px; padding: 18px; border: 1px solid #d8dee4; background: #fff; } header span { color: #68737e; font-size: .68rem; font-weight: 750; letter-spacing: .08em; } h2 { margin: 3px 0 0; color: #1f2d38; font-size: 1rem; } label { display: grid; gap: 6px; color: #46525d; font-size: .78rem; font-weight: 650; } input, textarea { box-sizing: border-box; width: 100%; border: 1px solid #cbd3da; border-radius: 4px; padding: 8px 10px; font: inherit; resize: vertical; } button { min-height: 36px; border: 1px solid #174f66; border-radius: 4px; padding: 7px 13px; color: #fff; background: #174f66; font: inherit; font-weight: 700; } button:disabled { border-color: #b7c0c7; background: #b7c0c7; }
</style>

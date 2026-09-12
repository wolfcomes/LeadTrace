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
  <form class="editor" aria-label="化合物核查" @submit.prevent="emit('save', { ...draft })">
    <header><span>COMPOUND REVIEW</span><h2>Paper-local 化合物</h2></header>
    <label>本地编号<input v-model="draft.localIdentity" name="local-identity" :disabled="!props.editable"></label>
    <label>显示标签<input v-model="draft.displayLabel" name="display-label" :disabled="!props.editable"></label>
    <label>创建或修改理由<textarea v-model="draft.reason" name="reason" rows="3" :disabled="!props.editable"></textarea></label>
    <button type="submit" :disabled="!canSave">保存草稿</button>
  </form>
</template>

<style scoped>
.editor { display: grid; gap: 13px; padding: 18px; border: 1px solid #d8dee4; background: #fff; } header span { color: #68737e; font-size: .68rem; font-weight: 750; letter-spacing: .08em; } h2 { margin: 3px 0 0; color: #1f2d38; font-size: 1rem; } label { display: grid; gap: 6px; color: #46525d; font-size: .78rem; font-weight: 650; } input, textarea { box-sizing: border-box; width: 100%; border: 1px solid #cbd3da; border-radius: 4px; padding: 8px 10px; font: inherit; resize: vertical; } button { min-height: 36px; border: 1px solid #174f66; border-radius: 4px; padding: 7px 13px; color: #fff; background: #174f66; font: inherit; font-weight: 700; } button:disabled { border-color: #b7c0c7; background: #b7c0c7; }
</style>

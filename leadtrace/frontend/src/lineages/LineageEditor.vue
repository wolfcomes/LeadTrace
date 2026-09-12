<script setup lang="ts">
import { reactive, watch } from "vue";

type LineageDraft = { lineageKey: string; parentCompoundId: string | null; derivedCompoundId: string; relationType: string; relationStatus: string; evidenceIds: string[]; reason: string };
const props = defineProps<{ modelValue: LineageDraft; readiness: { eligible: boolean; blockingCodes: string[] }; editable?: boolean }>();
const emit = defineEmits<{ "update:modelValue": [value: LineageDraft]; save: [value: LineageDraft] }>();
const draft = reactive<LineageDraft>({ ...props.modelValue, evidenceIds: [...props.modelValue.evidenceIds] });
watch(() => props.modelValue, (value) => Object.assign(draft, { ...value, evidenceIds: [...value.evidenceIds] }), { deep: true });
watch(draft, () => emit("update:modelValue", { ...draft, evidenceIds: [...draft.evidenceIds] }), { deep: true });
</script>

<template>
  <form class="editor" aria-label="谱系核查" @submit.prevent="emit('save', { ...draft, evidenceIds: [...draft.evidenceIds] })">
    <header><span>LINEAGE REVIEW</span><h2>谱系关系</h2></header>
    <div class="route"><label>父代 Compound ID<input v-model="draft.parentCompoundId" name="parent-compound-id" :disabled="!props.editable"></label><span aria-hidden="true">→</span><label>衍生 Compound ID<input v-model="draft.derivedCompoundId" name="derived-compound-id" :disabled="!props.editable"></label></div>
    <label>关系类型<input v-model="draft.relationType" name="relation-type" :disabled="!props.editable"></label>
    <label>关系状态<select v-model="draft.relationStatus" name="relation-status" :disabled="!props.editable"><option value="unresolved">未解析</option><option value="text_explicit">文本明确</option><option value="figure_explicit">图示明确</option><option value="human_confirmed">人工确认</option></select></label>
    <section data-pair-readiness :class="props.readiness.eligible ? 'ready' : 'blocked'"><strong>{{ props.readiness.eligible ? "Pair 可用" : "Pair 阻塞" }}</strong><span v-if="props.readiness.blockingCodes.length">{{ props.readiness.blockingCodes.join(" · ") }}</span></section>
    <label>修改理由<input v-model="draft.reason" name="reason" :disabled="!props.editable"></label>
    <button type="submit" :disabled="!props.editable || !draft.reason.trim()">保存草稿</button>
  </form>
</template>

<style scoped>
.editor { display: grid; gap: 13px; padding: 18px; border: 1px solid #d8dee4; background: #fff; } header span { color: #68737e; font-size: .68rem; font-weight: 750; letter-spacing: .08em; } h2 { margin: 3px 0 0; color: #1f2d38; font-size: 1rem; } label { display: grid; gap: 6px; color: #46525d; font-size: .78rem; font-weight: 650; } input, select { box-sizing: border-box; width: 100%; border: 1px solid #cbd3da; border-radius: 4px; padding: 8px 10px; font: inherit; } .route { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); align-items: end; gap: 10px; } .route > span { padding-bottom: 9px; color: #a87520; } section { display: grid; gap: 4px; border-left: 3px solid; padding: 9px 10px; font-size: .74rem; } section.ready { border-color: #17835c; color: #126447; background: #f1f8f4; } section.blocked { border-color: #b78024; color: #785619; background: #fff8e8; } section span { overflow-wrap: anywhere; } button { min-height: 36px; border: 1px solid #174f66; border-radius: 4px; padding: 7px 13px; color: #fff; background: #174f66; font: inherit; font-weight: 700; } button:disabled { border-color: #b7c0c7; background: #b7c0c7; }
</style>

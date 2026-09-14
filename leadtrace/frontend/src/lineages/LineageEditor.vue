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
  <form class="editor editor-form panel" aria-label="谱系核查" @submit.prevent="emit('save', { ...draft, evidenceIds: [...draft.evidenceIds] })">
    <header class="editor-heading"><span>LINEAGE REVIEW</span><h2>谱系关系</h2></header>
    <div class="route"><label class="form-field">父代 Compound ID<input v-model="draft.parentCompoundId" name="parent-compound-id" :disabled="!props.editable"></label><span aria-hidden="true">→</span><label class="form-field">衍生 Compound ID<input v-model="draft.derivedCompoundId" name="derived-compound-id" :disabled="!props.editable"></label></div>
    <label class="form-field">关系类型<input v-model="draft.relationType" name="relation-type" :disabled="!props.editable"></label>
    <label class="form-field">关系状态<select v-model="draft.relationStatus" name="relation-status" :disabled="!props.editable"><option value="unresolved">未解析</option><option value="text_explicit">文本明确</option><option value="figure_explicit">图示明确</option><option value="human_confirmed">人工确认</option></select></label>
    <section data-pair-readiness :class="['status-chip', props.readiness.eligible ? 'is-ok' : 'is-warning']"><strong>{{ props.readiness.eligible ? "Pair 可用" : "Pair 阻塞" }}</strong><span v-if="props.readiness.blockingCodes.length">{{ props.readiness.blockingCodes.join(" · ") }}</span></section>
    <label class="form-field">修改理由<input v-model="draft.reason" name="reason" :disabled="!props.editable"></label>
    <button class="button-primary" type="submit" :disabled="!props.editable || !draft.reason.trim()">保存草稿</button>
  </form>
</template>

<style scoped>
.route { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); align-items: end; gap: 10px; }
.route > span { padding-bottom: 9px; color: var(--coral-deep); }
@media (max-width: 560px) { .route { grid-template-columns: 1fr; } .route > span { padding: 0; transform: rotate(90deg); text-align: center; } }
</style>

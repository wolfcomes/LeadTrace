<script setup lang="ts">
import { onMounted, ref, useId, watch } from 'vue';
import { t } from '../i18n';
import { fetchPaperFilterOptions, filtersFromQuery, type PaperFilterOptions, type PaperFilterValues } from './paperFilters';
const props = defineProps<{ modelValue: PaperFilterValues }>();
const emit = defineEmits<{ apply: [value: PaperFilterValues] }>();
const draft = ref({ ...props.modelValue });
const id = useId();
const error = ref('');
const options = ref<PaperFilterOptions>({ journals: [], years: [], volumes: [], issues: [] });
watch(() => props.modelValue, value => { draft.value = { ...value }; error.value = ''; }, { deep: true });
onMounted(async () => { try { options.value = await fetchPaperFilterOptions(); } catch { /* Suggestions are optional; all filters remain editable. */ } });
function apply() {
  const { year_from: from, year_to: to } = draft.value;
  if ([from, to].some(value => value && (!/^\d{4}$/.test(value) || Number(value) < 1000)) || (from && to && Number(from) > Number(to))) {
    error.value = '请输入有效的年份范围，起始年份不能晚于结束年份。'; return;
  }
  error.value = ''; emit('apply', { ...draft.value });
}
function reset() { draft.value = filtersFromQuery({}); error.value = ''; emit('apply', { ...draft.value }); }
</script>
<template>
  <form class="paper-filters admin-panel" data-paper-filters :aria-label="t('文章筛选')" @submit.prevent="apply">
    <div class="paper-filter-grid">
      <label class="form-field">{{ t('期刊名称') }}<input v-model="draft.journal" name="journal" :list="`${id}-journals`" :placeholder="t('全部期刊')"></label>
      <label class="form-field">{{ t('起始年份') }}<input v-model="draft.year_from" name="year_from" type="text" inputmode="numeric" pattern="[0-9]{4}" :list="`${id}-years`" :placeholder="t('不限')"></label>
      <label class="form-field">{{ t('结束年份') }}<input v-model="draft.year_to" name="year_to" type="text" inputmode="numeric" pattern="[0-9]{4}" :list="`${id}-years`" :placeholder="t('不限')"></label>
      <label class="form-field">{{ t('卷（Volume）') }}<input v-model="draft.volume" name="volume" :list="`${id}-volumes`" :placeholder="t('全部卷')"></label>
      <label class="form-field">{{ t('期（Issue）') }}<input v-model="draft.issue" name="issue" :list="`${id}-issues`" :placeholder="t('全部期')"></label>
      <label class="form-field">{{ t('分配状态') }}<select v-model="draft.assignment_status" name="assignment_status"><option value="">{{ t('全部') }}</option><option value="assigned">{{ t('已分配') }}</option><option value="unassigned">{{ t('未分配') }}</option></select></label>
      <label class="form-field">{{ t('AI 预填状态') }}<select v-model="draft.prefill_status" name="prefill_status"><option value="">{{ t('全部') }}</option><option value="not_started">{{ t('未预填') }}</option><option value="queued">{{ t('排队中') }}</option><option value="running">{{ t('预填中') }}</option><option value="succeeded">{{ t('预填成功') }}</option><option value="failed">{{ t('预填失败') }}</option><option value="superseded">{{ t('已失效') }}</option></select></label>
      <div class="paper-filter-actions"><button class="button-primary" type="submit">{{ t('应用筛选') }}</button><button class="button-secondary" data-reset-filters type="button" @click="reset">{{ t('重置筛选') }}</button></div>
    </div>
    <p v-if="error" class="inline-feedback is-error" role="alert">{{ t(error) }}</p>
    <datalist :id="`${id}-journals`"><option v-for="value in options.journals" :key="value" :value="value" /></datalist>
    <datalist :id="`${id}-years`"><option v-for="value in options.years" :key="value" :value="value" /></datalist>
    <datalist :id="`${id}-volumes`"><option v-for="value in options.volumes" :key="value" :value="value" /></datalist>
    <datalist :id="`${id}-issues`"><option v-for="value in options.issues" :key="value" :value="value" /></datalist>
  </form>
</template>
<style scoped>
.paper-filters { padding: 1rem; margin: 1rem 0; }
.paper-filter-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .8rem 1rem; align-items: end; }
.form-field { min-width: 0; }
.form-field input, .form-field select { width: 100%; min-width: 0; box-sizing: border-box; }
.paper-filter-actions { display: flex; gap: .5rem; flex-wrap: wrap; align-items: center; }
@media (max-width: 900px) { .paper-filter-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 480px) { .paper-filter-grid { grid-template-columns: minmax(0, 1fr); } }
</style>

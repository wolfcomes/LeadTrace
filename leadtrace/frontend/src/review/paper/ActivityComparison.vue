<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { t } from '../../i18n';
import { getActivityComparison } from '../../v2/api';
import type { ActivityComparison, PaperWorkspace } from '../../v2/types';
import { activityMatrix, measurementGroups, orderByMeasurementSimilarity } from './activityComparison';
import ReviewHint from './ReviewHint.vue';

const props = defineProps<{workspace: PaperWorkspace; active: boolean; blocked?: boolean}>();
const emit = defineEmits<{open: [compoundId: string, activityId?: string]}>();
const data = ref<ActivityComparison>();
const loading = ref(false), error = ref('');
const search = ref('');
const sort = ref<'similarity' | 'default' | 'label'>('similarity');
const selectedGroups = ref<string[] | null>(null);
const showEmpty = ref(false);
const selectedColumns = ref<string[] | null>(null);
const viewport = ref<HTMLElement>();
let sequence = 0;
let position = {top: 0, left: 0};
const matrix = computed(() => activityMatrix(data.value?.activities ?? []));
const groups = computed(() => measurementGroups(data.value?.activities ?? []));
const activeGroups = computed(() => groups.value.filter(g => selectedGroups.value?.includes(g.key)));
const availableColumns = computed(() => activeGroups.value.flatMap(g => g.columns));
const columns = computed(() => availableColumns.value.filter(c => selectedColumns.value?.includes(c.key)));
const collator = new Intl.Collator('en', {numeric: true, sensitivity: 'base'});
const matchingCompounds = computed(() => {
  const query = search.value.trim().toLocaleLowerCase();
  return (data.value?.compounds ?? []).filter(c => `${c.compound_label} ${c.display_name ?? ''}`.toLocaleLowerCase().includes(query));
});
const hasSelectedMeasurement = (id: string) => columns.value.some(c => matrix.value.cells.get(id)?.get(c.key)?.length);
const missingCount = computed(() => matchingCompounds.value.filter(c => !hasSelectedMeasurement(c.id)).length);
const compounds = computed(() => {
  if (!columns.value.length) return [];
  const rows = matchingCompounds.value.filter(c => showEmpty.value || hasSelectedMeasurement(c.id));
  if (sort.value === 'similarity') return orderByMeasurementSimilarity(rows, matrix.value.cells, columns.value.map(c => c.key));
  return sort.value === 'label' ? rows.sort((a,b) => collator.compare(a.compound_label, b.compound_label)) : rows;
});
function focusGroup(key: string) {
  const group = groups.value.find(g => g.key === key);
  selectedGroups.value = group ? [key] : [];
  selectedColumns.value = group?.columns[0] ? [group.columns[0].key] : [];
  position = {top: 0, left: 0}; void restoreScroll();
}
function toggleGroup(key: string, checked: boolean) {
  const selected = new Set(selectedGroups.value ?? []);
  if (checked) selected.add(key); else selected.delete(key);
  selectedGroups.value = [...selected];
  const columnKeys = new Set(activeGroups.value.flatMap(g => g.columns.map(c => c.key)));
  const keep = (selectedColumns.value ?? []).filter(k => columnKeys.has(k));
  const first = groups.value.find(g => g.key === key)?.columns[0];
  if (checked && first && !keep.includes(first.key)) keep.push(first.key);
  selectedColumns.value = keep;
}
function toggleColumn(key: string, checked: boolean) {
  const selected = new Set(selectedColumns.value ?? []);
  if (checked) selected.add(key); else selected.delete(key);
  selectedColumns.value = [...selected];
}
function rememberScroll() {
  if (props.active && !loading.value && viewport.value) position = {top: viewport.value.scrollTop, left: viewport.value.scrollLeft};
}
async function restoreScroll() {
  await nextTick();
  if (props.active && viewport.value) { viewport.value.scrollTop = position.top; viewport.value.scrollLeft = position.left; }
}
async function load() {
  const epoch = ++sequence, id = props.workspace.id;
  loading.value = true; error.value = '';
  try {
    const result = await getActivityComparison(id);
    if (epoch !== sequence || id !== props.workspace.id) return;
    if (result.workspace_id !== id || result.workspace_version < props.workspace.version) throw new Error('Stale comparison');
    data.value = result;
    if (selectedGroups.value === null && groups.value.length) {
      const first = groups.value[0];
      selectedGroups.value = first ? [first.key] : [];
      selectedColumns.value = first?.columns[0] ? [first.columns[0].key] : [];
    }
  } catch {
    if (epoch === sequence) error.value = '活性对比暂时无法读取，请重试。';
  } finally {
    if (epoch === sequence) { loading.value = false; await restoreScroll(); }
  }
}
function open(compoundId: string, activityId?: string) {
  if (props.blocked || loading.value || error.value || !props.active) return;
  rememberScroll();
  if (activityId) emit('open', compoundId, activityId); else emit('open', compoundId);
}
watch(() => [props.workspace.id, props.active, props.workspace.version] as const, ([id, active], previous) => {
  if (previous && previous[0] !== id) {
    sequence++; data.value = undefined; search.value = ''; sort.value = 'similarity'; selectedGroups.value = null; selectedColumns.value = null; showEmpty.value = false; position = {top:0, left:0};
  }
  if (active && (!previous?.[1] || id !== previous[0] || data.value?.workspace_version !== props.workspace.version)) void load();
}, {immediate:true});
onBeforeUnmount(() => { sequence++; });
</script>

<template>
  <section class="activity-comparison" data-activity-comparison>
    <header class="comparison-heading"><div><h2>{{ t('活性对比') }}</h2><p>{{ t('只读 · 已保存的活性数据；点击数值查看对应记录。') }}</p></div>
      <button type="button" class="button-secondary" :disabled="loading" data-comparison-refresh @click="load">{{ t('刷新') }}</button>
    </header>
    <div class="comparison-toolbar">
      <label class="form-field comparison-group-select">{{ t('测定分组') }}<select data-comparison-group :value="activeGroups.length === 1 ? activeGroups[0]!.key : ''" @change="focusGroup(($event.target as HTMLSelectElement).value)"><option value="" disabled>{{ activeGroups.length > 1 ? t('已选择多个测定组') : t('请选择测定分组') }}</option><option v-for="group in groups" :key="group.key" :value="group.key">{{ group.assay }} · {{ group.metric }} · {{ group.unit || t('未记录单位') }} ({{ group.compoundCount }})</option></select></label>
      <label class="form-field">{{ t('搜索编号或名称') }}<input v-model="search" data-comparison-search type="search" :placeholder="t('搜索编号或名称')"></label>
      <label class="form-field">{{ t('排序方式') }}<select v-model="sort" data-comparison-sort><option value="similarity">{{ t('相似测定组合') }}</option><option value="label">{{ t('名称排序') }}</option><option value="default">{{ t('默认排序') }}</option></select></label>
    </div>
    <div class="comparison-options">
      <details class="measurement-picker" data-comparison-groups><summary>{{ t('多组对比') }} ({{ activeGroups.length }}/{{ groups.length }})</summary>
        <div class="measurement-options"><label v-for="group in groups" :key="group.key"><input type="checkbox" data-comparison-group-choice :value="group.key" :checked="selectedGroups?.includes(group.key)" @change="toggleGroup(group.key, ($event.target as HTMLInputElement).checked)"><span>{{ group.assay }} · {{ group.metric }} · {{ group.unit || t('未记录单位') }}<small>{{ t('{count} 个 Compound', {count: group.compoundCount}) }}</small></span></label></div>
      </details>
      <details class="measurement-picker" data-comparison-conditions><summary>{{ t('实验条件') }} ({{ columns.length }}/{{ availableColumns.length }})</summary>
        <div class="measurement-options">
          <div class="editor-actions"><button type="button" class="button-quiet" data-comparison-all-columns @click="selectedColumns = availableColumns.map(c => c.key)">{{ t('选择全部条件') }}</button><button type="button" class="button-quiet" data-comparison-clear-columns @click="selectedColumns = []">{{ t('清空选择') }}</button></div>
          <fieldset v-for="group in activeGroups" :key="group.key"><legend>{{ group.assay }} · {{ group.metric }} · {{ group.unit || t('未记录单位') }}</legend><label v-for="column in group.columns" :key="column.key"><input type="checkbox" data-comparison-column-choice :value="column.key" :checked="selectedColumns?.includes(column.key)" @change="toggleColumn(column.key, ($event.target as HTMLInputElement).checked)"><span>{{ column.context || t('未记录实验条件') }}<small>{{ t('{count} 个 Compound', {count: column.compoundCount}) }}</small></span></label></fieldset>
        </div>
      </details>
    </div>
    <p v-if="blocked" class="inline-feedback is-warning">{{ t('请先保存或取消当前编辑，再打开其他条目。') }}</p>
    <p v-if="loading" role="status">{{ t('正在读取活性对比…') }}</p>
    <p v-if="error" role="alert">{{ t(error) }} <button type="button" class="button-quiet" data-comparison-retry @click="load">{{ t('重试') }}</button></p>
    <template v-if="data && !error">
      <p v-if="!data.compounds.length && !loading">{{ t('当前文章尚无 Compound。') }}</p>
      <p v-else-if="!data.activities.length && !loading">{{ t('当前文章尚无活性记录。') }}</p>
      <p v-else-if="!columns.length && !loading">{{ t('请选择要比较的实验条件。') }}</p>
      <p v-if="columns.length && data.compounds.length && !compounds.length && !loading">{{ t('没有匹配的 Compound。') }}</p>
      <div v-if="columns.length && !loading" class="comparison-coverage">
        <span>{{ t('显示 {shown}/{total} 个 Compound', {shown: compounds.length, total: matchingCompounds.length}) }}</span>
        <label v-if="missingCount || showEmpty"><input v-model="showEmpty" data-comparison-show-empty type="checkbox"><span data-comparison-hidden-count>{{ t('显示无所选条件记录的 Compound（{count}）', {count: missingCount}) }}</span></label>
      </div>
      <div v-show="!loading && compounds.length > 0" ref="viewport" class="comparison-scroll" data-comparison-scroll tabindex="0" role="region" :aria-label="t('Compound 活性对比表')" @scroll="rememberScroll">
        <table class="comparison-grid">
          <caption>{{ t('— 表示无对应记录；不同条件或单位分别列出，同格多条记录全部保留。') }}</caption>
          <thead><tr><th scope="col" class="compound-column">Compound</th><th v-for="column in columns" :key="column.key" scope="col" data-comparison-column><span class="measurement-assay" :title="column.assay">{{ column.assay }}</span><small>{{ column.metric }} · {{ column.unit || t('未记录单位') }}</small><details v-if="column.context" class="measurement-context"><summary :title="column.context">{{ column.context }}</summary><p>{{ column.context }}</p></details><small v-else>{{ t('未记录实验条件') }}</small></th></tr></thead>
          <tbody><tr v-for="compound in compounds" :key="compound.id" data-comparison-row :data-compound-id="compound.id">
            <th scope="row" class="compound-column"><button type="button" class="comparison-link" data-comparison-compound :disabled="blocked || loading" @click="open(compound.id)">{{ compound.compound_label }}</button><details v-if="compound.display_name" class="compound-name"><summary :title="compound.display_name">{{ t('名称') }}</summary><small>{{ compound.display_name }}</small></details><ReviewHint :hint="compound.review_hint" /></th>
            <td v-for="column in columns" :key="column.key">
              <template v-if="matrix.cells.get(compound.id)?.get(column.key)?.length">
                <div v-for="activity in matrix.cells.get(compound.id)?.get(column.key)" :key="activity.id" class="measurement-value"><button type="button" class="comparison-link" data-comparison-activity :data-activity-id="activity.id" :disabled="blocked || loading" :aria-label="t('查看 {compound} 的活性记录：{value}', {compound: compound.compound_label, value: `${activity.operator} ${activity.value} ${activity.unit ?? ''}`})" @click="open(compound.id, activity.id)">{{ activity.operator }} {{ activity.value }}</button><ReviewHint :hint="activity.review_hint" /></div>
              </template><span v-else class="missing-measurement">—</span>
            </td>
          </tr></tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<style scoped>
.activity-comparison { min-width: 0; }
.comparison-heading, .comparison-toolbar { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; }
.comparison-heading h2 { margin: 0; }
.comparison-heading p { color: var(--muted); font-size: .82rem; }
.comparison-toolbar { justify-content: flex-start; margin: 16px 0; align-items: flex-end; }
.comparison-toolbar .form-field { min-width: 150px; }
.comparison-toolbar .comparison-group-select { flex: 1 1 260px; min-width: 0; }
.comparison-group-select select { width: 100%; text-overflow: ellipsis; }
.comparison-options, .comparison-coverage { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin: 12px 0; }
.comparison-coverage { justify-content: space-between; color: var(--muted); font-size: .75rem; }
.comparison-coverage label { display: flex; align-items: center; gap: 6px; }
.comparison-coverage input { width: auto; min-height: auto; }
.measurement-options fieldset { border: 0; padding: 10px 0; margin: 0; min-width: 0; }
.measurement-options legend { font-weight: 600; overflow-wrap: anywhere; }
.measurement-assay { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.compound-name { display: inline-block; margin-left: 6px; font-size: .7rem; font-weight: normal; }
.compound-name summary { cursor: pointer; color: var(--muted); }
.measurement-picker { position: relative; max-width: 100%; padding: 10px; border: 1px solid var(--line); border-radius: 6px; }
.measurement-picker summary { cursor: pointer; }
.measurement-options { max-height: 300px; max-width: min(600px, 80vw); overflow: auto; }
.measurement-options label { display: flex; align-items: flex-start; gap: 8px; padding: 8px 0; overflow-wrap: anywhere; }
.measurement-options input { flex: 0 0 auto; width: auto; min-height: auto; margin-top: 4px; }
small { display: block; font-weight: normal; font-size: .75rem; color: var(--muted); overflow-wrap: anywhere; }
.comparison-scroll { max-height: 65vh; overflow: auto; border: 1px solid var(--line); border-radius: 6px; }
.comparison-grid { border-collapse: separate; border-spacing: 0; width: max-content; min-width: min(100%, 480px); font-size: .85rem; }
caption { caption-side: bottom; text-align: left; padding: 12px; color: var(--muted); font-size: .75rem; }
th, td { padding: 8px 10px; border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; min-width: 150px; max-width: 210px; overflow-wrap: anywhere; }
thead th { position: sticky; top: 0; background: var(--paper); z-index: 2; }
.compound-column { position: sticky; left: 0; background: var(--paper); z-index: 1; min-width: 100px; max-width: 140px; }
thead .compound-column { z-index: 3; }
.measurement-context { font-size: .75rem; font-weight: normal; margin-top: 6px; }
.measurement-context summary { cursor: pointer; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.measurement-context p { white-space: pre-wrap; }
.measurement-value { display: flex; align-items: baseline; gap: 6px; margin-bottom: 4px; }
.comparison-link { border: 0; background: transparent; padding: 2px 0; color: var(--teal); text-decoration: underline; text-underline-offset: 3px; cursor: pointer; text-align: left; font: inherit; font-variant-numeric: tabular-nums; }
.comparison-link:disabled { cursor: default; opacity: .55; }
.missing-measurement { color: var(--muted); }
@media (max-width: 600px) { .comparison-toolbar .form-field { flex: 1 1 140px; } th, td { min-width: 140px; } .compound-column { min-width: 85px; max-width: 110px; } }
</style>

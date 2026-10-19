<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { t } from '../../i18n';
import { getActivityComparison } from '../../v2/api';
import type { ActivityComparison, PaperWorkspace } from '../../v2/types';
import { activityMatrix } from './activityComparison';
import ReviewHint from './ReviewHint.vue';

const props = defineProps<{workspace: PaperWorkspace; active: boolean; blocked?: boolean}>();
const emit = defineEmits<{open: [compoundId: string, activityId?: string]}>();
const data = ref<ActivityComparison>();
const loading = ref(false), error = ref('');
const search = ref('');
const sort = ref<'default' | 'label'>('default');
const selectedColumns = ref<string[] | null>(null);
const viewport = ref<HTMLElement>();
let sequence = 0;
let position = {top: 0, left: 0};
const matrix = computed(() => activityMatrix(data.value?.activities ?? []));
const columns = computed(() => matrix.value.columns.filter(c => selectedColumns.value === null || selectedColumns.value.includes(c.key)));
const collator = new Intl.Collator('en', {numeric: true, sensitivity: 'base'});
const compounds = computed(() => {
  const query = search.value.trim().toLocaleLowerCase();
  const rows = (data.value?.compounds ?? []).filter(c => `${c.compound_label} ${c.display_name ?? ''}`.toLocaleLowerCase().includes(query));
  return sort.value === 'label' ? rows.sort((a,b) => collator.compare(a.compound_label, b.compound_label)) : rows;
});
function toggleColumn(key: string, checked: boolean) {
  const selected = new Set(selectedColumns.value ?? matrix.value.columns.map(c => c.key));
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
    sequence++; data.value = undefined; search.value = ''; sort.value = 'default'; selectedColumns.value = null; position = {top:0, left:0};
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
      <label class="form-field">{{ t('搜索编号或名称') }}<input v-model="search" data-comparison-search type="search" :placeholder="t('搜索编号或名称')"></label>
      <label class="form-field">{{ t('排序方式') }}<select v-model="sort" data-comparison-sort><option value="default">{{ t('默认排序') }}</option><option value="label">{{ t('名称排序') }}</option></select></label>
      <details class="measurement-picker"><summary>{{ t('测定项目') }} ({{ columns.length }}/{{ matrix.columns.length }})</summary>
        <div class="measurement-options">
          <div class="editor-actions"><button type="button" class="button-quiet" @click="selectedColumns = null">{{ t('选择全部测定') }}</button><button type="button" class="button-quiet" data-comparison-clear-columns @click="selectedColumns = []">{{ t('清空选择') }}</button></div>
          <label v-for="column in matrix.columns" :key="column.key"><input type="checkbox" data-comparison-column-choice :checked="selectedColumns === null || selectedColumns.includes(column.key)" @change="toggleColumn(column.key, ($event.target as HTMLInputElement).checked)"><span>{{ column.assay }} · {{ column.metric }} · {{ column.unit || t('未记录单位') }}<small>{{ column.context || t('未记录实验条件') }}</small></span></label>
        </div>
      </details>
    </div>
    <p v-if="blocked" class="inline-feedback is-warning">{{ t('请先保存或取消当前编辑，再打开其他条目。') }}</p>
    <p v-if="loading" role="status">{{ t('正在读取活性对比…') }}</p>
    <p v-if="error" role="alert">{{ t(error) }} <button type="button" class="button-quiet" data-comparison-retry @click="load">{{ t('重试') }}</button></p>
    <template v-if="data && !error">
      <p v-if="!data.compounds.length && !loading">{{ t('当前文章尚无 Compound。') }}</p>
      <p v-else-if="!data.activities.length && !loading">{{ t('当前文章尚无活性记录。') }}</p>
      <p v-else-if="!columns.length && !loading">{{ t('请选择要比较的测定项目。') }}</p>
      <p v-if="data.compounds.length && !compounds.length && !loading">{{ t('没有匹配的 Compound。') }}</p>
      <div v-show="!loading && compounds.length > 0" ref="viewport" class="comparison-scroll" data-comparison-scroll tabindex="0" role="region" :aria-label="t('Compound 活性对比表')" @scroll="rememberScroll">
        <table class="comparison-grid">
          <caption>{{ t('— 表示无对应记录；不同条件或单位分别列出，同格多条记录全部保留。') }}</caption>
          <thead><tr><th scope="col" class="compound-column">Compound</th><th v-for="column in columns" :key="column.key" scope="col" data-comparison-column><span>{{ column.assay }}</span><small>{{ column.metric }} · {{ column.unit || t('未记录单位') }}</small><details v-if="column.context" class="measurement-context"><summary :title="column.context">{{ column.context }}</summary><p>{{ column.context }}</p></details><small v-else>{{ t('未记录实验条件') }}</small></th></tr></thead>
          <tbody><tr v-for="compound in compounds" :key="compound.id" data-comparison-row :data-compound-id="compound.id">
            <th scope="row" class="compound-column"><button type="button" class="comparison-link" data-comparison-compound :disabled="blocked || loading" @click="open(compound.id)">{{ compound.compound_label }}</button><small v-if="compound.display_name">{{ compound.display_name }}</small><ReviewHint :hint="compound.review_hint" /></th>
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
.comparison-heading, .comparison-toolbar { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; }
.comparison-heading h2 { margin: 0; }
.comparison-heading p { color: var(--muted); font-size: .82rem; }
.comparison-toolbar { justify-content: flex-start; margin: 16px 0; align-items: flex-end; }
.comparison-toolbar .form-field { min-width: 160px; }
.measurement-picker { position: relative; max-width: 100%; padding: 10px; border: 1px solid var(--line); border-radius: 6px; }
.measurement-picker summary { cursor: pointer; }
.measurement-options { max-height: 300px; max-width: min(600px, 80vw); overflow: auto; }
.measurement-options label { display: flex; align-items: flex-start; gap: 8px; padding: 8px 0; overflow-wrap: anywhere; }
.measurement-options input { flex: 0 0 auto; width: auto; min-height: auto; margin-top: 4px; }
small { display: block; font-weight: normal; font-size: .75rem; color: var(--muted); overflow-wrap: anywhere; }
.comparison-scroll { max-height: 65vh; overflow: auto; border: 1px solid var(--line); border-radius: 6px; }
.comparison-grid { border-collapse: separate; border-spacing: 0; width: max-content; min-width: 100%; font-size: .85rem; }
caption { caption-side: bottom; text-align: left; padding: 12px; color: var(--muted); font-size: .75rem; }
th, td { padding: 12px; border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; min-width: 190px; max-width: 260px; overflow-wrap: anywhere; }
thead th { position: sticky; top: 0; background: var(--paper); z-index: 2; }
.compound-column { position: sticky; left: 0; background: var(--paper); z-index: 1; min-width: 150px; max-width: 190px; }
thead .compound-column { z-index: 3; }
.measurement-context { font-size: .75rem; font-weight: normal; margin-top: 6px; }
.measurement-context summary { cursor: pointer; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.measurement-context p { white-space: pre-wrap; }
.measurement-value { display: flex; align-items: baseline; gap: 6px; margin-bottom: 4px; }
.comparison-link { border: 0; background: transparent; padding: 2px 0; color: var(--teal); text-decoration: underline; text-underline-offset: 3px; cursor: pointer; text-align: left; font: inherit; font-variant-numeric: tabular-nums; }
.comparison-link:disabled { cursor: default; opacity: .55; }
.missing-measurement { color: var(--muted); }
@media (max-width: 600px) { .comparison-toolbar .form-field { flex: 1 1 140px; } th, td { min-width: 170px; } .compound-column { min-width: 110px; max-width: 130px; } }
</style>

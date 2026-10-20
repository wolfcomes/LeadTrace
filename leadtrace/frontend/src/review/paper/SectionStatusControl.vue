<script setup lang="ts">
import { computed } from "vue";
import { useReviewProgress } from "./useReviewProgress";
import { t } from "../../i18n";
import type { PaperWorkspace } from "../../v2/types";
import type { SectionState } from "./usePaperWorkspace";
type WorkspaceSection = PaperWorkspace["sections"][number];
const props = defineProps<{ groupKey: string; sections: WorkspaceSection[]; disabled?: boolean; saving?: boolean }>();
const progress = useReviewProgress();
const coverage = computed(() => progress?.progress.value?.sections.find(x => x.section_key === props.groupKey));
const lineageCounts = computed(() => ['lineage', 'edge'].map(kind => {
  const items = progress?.progress.value?.items.filter(item => item.kind === kind) ?? [];
  return { kind, label: kind === 'lineage' ? 'Lineage 条目' : 'Edge 条目', total: items.length, viewed: items.filter(item => item.viewed).length };
}));
const labels: Record<string, string> = { bibliography: "文章信息", compounds: "化合物", activities: "活性表", lineages: "Lineage" };
const sectionState = computed(() => {
  const states = props.sections.map(section => section.state);
  return states.length && states.every(state => state === states[0]) ? states[0] : "pending";
});
const effectiveState = computed(() => coverage.value?.complete ? 'completed' : sectionState.value);
const progressLabel = computed(() => coverage.value?.complete
  ? (props.groupKey === 'activities' ? '活性表已自动完成' : '阅读已自动确认')
  : '条目查看进度');
const emit = defineEmits<{ change: [state: SectionState] }>();
const choices: Array<{ value: SectionState; label: string }> = [{ value: "pending", label: "待处理" }, { value: "completed", label: "完成" }, { value: "not_reported", label: "未报告" }];
</script>
<template>
  <article class="section-status-control" data-section-status :data-section-key="groupKey" :data-state="effectiveState" :class="{'is-viewed':coverage?.complete}">
    <div><strong>{{ t(labels[groupKey]) }}</strong><small v-if="saving">{{ t("正在保存…") }}</small></div>
    <template v-if="coverage && groupKey === 'lineages'">
      <small v-for="count in lineageCounts" :key="count.kind" :data-view-progress="count.kind">{{ t(count.label) }} {{ count.viewed }} / {{ count.total }}</small>
      <small v-if="coverage.complete">{{ t('阅读已自动确认') }}</small>
    </template>
    <small v-else-if="coverage">{{ t(progressLabel) }} {{ coverage.viewed }} / {{ coverage.total }}</small>
    <div class="segmented-control" :aria-label="t('{p0}区段状态', { p0: t(labels[groupKey]) })"><button v-for="choice in choices" :key="choice.value" type="button" :data-section-choice="choice.value" :aria-pressed="effectiveState === choice.value" :disabled="disabled || saving || (coverage?.complete && choice.value !== 'completed')" @click="emit('change', choice.value)">{{ t(choice.label) }}</button></div>
  </article>
</template>

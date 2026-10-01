<script setup lang="ts">
import { computed } from "vue";
import { useReviewProgress } from "./useReviewProgress";
import { t } from "../../i18n";
import type { PaperWorkspace } from "../../v2/types";
import type { SectionState } from "./usePaperWorkspace";
type WorkspaceSection = PaperWorkspace["sections"][number];
const props = defineProps<{ section: WorkspaceSection; disabled?: boolean; saving?: boolean }>();
const progress = useReviewProgress();
const viewGroup: Record<string,string> = {compounds:'compounds',structures:'compounds',activities:'compounds',lineages:'lineages',edge_evidence:'lineages'};
const coverage = computed(() => progress?.progress.value?.sections.find(x => x.section_key === viewGroup[props.section.section_key]));
const showsCount = computed(() => ['compounds','lineages'].includes(props.section.section_key));
const effectiveState = computed(() => coverage.value?.complete ? 'completed' : props.section.state);
const emit = defineEmits<{ change: [state: SectionState] }>();
const labels: Record<WorkspaceSection["section_key"], string> = { bibliography: "文章信息", compounds: "化合物", structures: "结构", lineages: "Lineage", edge_evidence: "Edge Evidence", activities: "活性" };
const choices: Array<{ value: SectionState; label: string }> = [{ value: "pending", label: "待处理" }, { value: "completed", label: "完成" }, { value: "not_reported", label: "未报告" }];
</script>
<template>
  <article class="section-status-control" data-section-status :data-section-key="section.section_key" :data-state="effectiveState" :class="{'is-viewed':coverage?.complete}">
    <div><strong>{{ t(labels[section.section_key]) }}</strong><small v-if="saving">{{ t("正在保存…") }}</small></div>
    <small v-if="coverage && showsCount">{{ t(coverage.complete ? '阅读已自动确认' : '条目查看进度') }} {{ coverage.viewed }} / {{ coverage.total }}</small>
    <div class="segmented-control" :aria-label="t('{p0}区段状态', { p0: t(labels[section.section_key]) })"><button v-for="choice in choices.filter(x => !coverage || x.value !== 'completed')" :key="choice.value" type="button" :data-section-choice="choice.value" :aria-pressed="effectiveState === choice.value" :disabled="disabled || saving" @click="emit('change', choice.value)">{{ t(choice.label) }}</button></div>
  </article>
</template>

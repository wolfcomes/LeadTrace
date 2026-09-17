<script setup lang="ts">
import type { PaperWorkspace } from "../../v2/types";
import type { SectionState } from "./usePaperWorkspace";
type WorkspaceSection = PaperWorkspace["sections"][number];
defineProps<{ section: WorkspaceSection; disabled?: boolean; saving?: boolean }>();
const emit = defineEmits<{ change: [state: SectionState] }>();
const labels: Record<WorkspaceSection["section_key"], string> = { bibliography: "文章信息", compounds: "化合物", structures: "结构", lineages: "Lineage", edge_evidence: "Edge Evidence", activities: "活性" };
const choices: Array<{ value: SectionState; label: string }> = [{ value: "pending", label: "待处理" }, { value: "completed", label: "完成" }, { value: "not_reported", label: "未报告" }];
</script>
<template>
  <article class="section-status-control" data-section-status :data-section-key="section.section_key" :data-state="section.state">
    <div><strong>{{ labels[section.section_key] }}</strong><small v-if="saving">正在保存…</small></div>
    <div class="segmented-control" :aria-label="`${labels[section.section_key]}区段状态`"><button v-for="choice in choices" :key="choice.value" type="button" :data-section-choice="choice.value" :aria-pressed="section.state === choice.value" :disabled="disabled || saving" @click="emit('change', choice.value)">{{ choice.label }}</button></div>
  </article>
</template>

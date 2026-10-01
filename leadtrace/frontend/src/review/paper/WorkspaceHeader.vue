<script setup lang="ts">
import { t } from "../../i18n";
import type { PaperWorkspace } from "../../v2/types";
defineProps<{ workspace: PaperWorkspace }>();
function stateLabel(workspace: PaperWorkspace): string {
  if (workspace.state === "approved") return "已批准 · 只读";
  if (workspace.state === "submitted") return "已提交 · 待审批";
  if (workspace.task_status === "changes_requested") return "Admin 已退回修改";
  return "编辑中";
}
</script>
<template>
  <header class="workspace-header page-heading">
    <div><RouterLink class="back-link" to="/review/tasks">{{ t("← 返回我的任务") }}</RouterLink><p class="eyebrow">{{ workspace.bibliography.paper_key }}</p><h1>{{ workspace.bibliography.title }}</h1><p>{{ workspace.bibliography.journal }} · {{ workspace.bibliography.publication_year }} · Volume {{ workspace.bibliography.volume }} · Issue {{ workspace.bibliography.issue }}</p></div>
    <div class="workspace-header-actions"><div class="workspace-version-summary"><span class="status-chip" :data-state="workspace.state">{{ t(stateLabel(workspace)) }}</span><code data-workspace-version>Workspace v{{ workspace.version }}</code></div><a class="button-secondary" data-source-pdf :href="`/api/v2/papers/${workspace.bibliography.paper_id}/source-pdf`" target="_blank" rel="noopener">{{ t("打开 Source PDF ↗") }}</a></div>
  </header>
</template>

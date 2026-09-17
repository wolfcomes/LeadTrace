<script setup lang="ts">
import { computed, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { useAuthStore } from "../../auth/store";
import ActivityEditor from "./ActivityEditor.vue";
import CompoundList from "./CompoundList.vue";
import EvidenceEditor from "./EvidenceEditor.vue";
import LineageEditor from "./LineageEditor.vue";
import SectionStatusControl from "./SectionStatusControl.vue";
import SubmissionChecklist from "./SubmissionChecklist.vue";
import { usePaperWorkspace } from "./usePaperWorkspace";
import WorkspaceHeader from "./WorkspaceHeader.vue";

const tabs = [
  { key: "bibliography", label: "文章信息" },
  { key: "compounds", label: "化合物与结构" },
  { key: "lineages", label: "Lineage" },
  { key: "evidence", label: "证据与活性" },
  { key: "submit", label: "检查与提交" },
] as const;
type TabKey = typeof tabs[number]["key"];

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const workspaceState = usePaperWorkspace(route, router);
const activeTab = computed<TabKey>(() => {
  const value = route.query.tab;
  return tabs.some((tab) => tab.key === value) ? value as TabKey : "bibliography";
});
const canEdit = computed(() => (
  auth.user?.role === "reviewer"
  && workspaceState.workspace.value?.state === "editing"
));
const readOnly = computed(() => !canEdit.value);

function selectTab(tab: TabKey): void {
  void router.replace({ path: route.path, query: { ...route.query, tab } });
}

function selectCompound(compoundId: string): void {
  void router.replace({ path: route.path, query: { ...route.query, entity: compoundId } });
}

function selectEntity(entityId: string): void {
  void router.replace({ path: route.path, query: { ...route.query, entity: entityId } });
}

function focusRecord(tab: "bibliography" | "compounds" | "lineages" | "evidence", entityId?: string): void {
  const { entity: _currentEntity, ...preservedQuery } = route.query;
  const query = { ...preservedQuery, tab, ...(entityId ? { entity: entityId } : {}) };
  void router.replace({ path: route.path, query });
}

function refreshWorkspace(): void {
  void workspaceState.reload();
}

async function synchronizeWorkspace(): Promise<void> {
  const paperId = String(route.params.paperId ?? "");
  const hintedWorkspaceId = typeof route.query.workspace === "string" ? route.query.workspace : undefined;
  const current = workspaceState.workspace.value;
  if (
    hintedWorkspaceId
    && current?.id === hintedWorkspaceId
    && current.bibliography.paper_id === paperId
  ) return;
  await workspaceState.open();
}

watch(
  [() => route.params.paperId, () => route.query.workspace],
  synchronizeWorkspace,
  { immediate: true },
);
</script>

<template>
  <div class="review-page paper-workspace-shell" data-paper-workspace>
    <section v-if="workspaceState.state.value === 'loading'" class="page-state" aria-live="polite"><span class="state-spinner" aria-hidden="true"></span><p>正在读取 Paper Workspace…</p></section>
    <section v-else-if="workspaceState.state.value === 'not-found'" class="page-state"><span class="state-symbol">404</span><h1>未找到分配任务</h1><p>请从“我的任务”重新进入。</p></section>
    <section v-else-if="workspaceState.state.value === 'error'" class="page-state" role="alert"><span class="state-symbol is-error">!</span><h1>暂时无法读取 Workspace</h1><small v-if="workspaceState.requestId.value">请求编号 · {{ workspaceState.requestId.value }}</small><button class="button-secondary" type="button" @click="workspaceState.open">重新加载</button></section>

    <template v-else-if="workspaceState.workspace.value">
      <WorkspaceHeader :workspace="workspaceState.workspace.value" />
      <p v-if="auth.user?.role === 'admin'" class="inline-feedback is-warning" data-admin-readonly>Admin 查看模式：此 Workspace 只读。</p>
      <p v-if="workspaceState.concurrencyMessage.value" class="inline-feedback is-warning" data-concurrency-alert role="alert">{{ workspaceState.concurrencyMessage.value }}</p>
      <p v-if="workspaceState.actionError.value" class="inline-feedback is-error" role="alert">{{ workspaceState.actionError.value }}</p>

      <section class="workspace-section-status" aria-label="六个固定区段状态">
        <SectionStatusControl
          v-for="section in workspaceState.workspace.value.sections"
          :key="section.section_key"
          :section="section"
          :disabled="readOnly"
          :saving="workspaceState.savingSection.value === section.section_key"
          @change="workspaceState.setSectionState(section.section_key, $event)"
        />
      </section>

      <nav class="workspace-tabs paper-workspace-tabs" data-workspace-tabs aria-label="Paper Workspace">
        <button v-for="tab in tabs" :key="tab.key" type="button" data-workspace-tab :aria-current="activeTab === tab.key ? 'page' : undefined" @click="selectTab(tab.key)">{{ tab.label }}</button>
      </nav>

      <section class="workspace-editor-surface panel">
        <template v-if="activeTab === 'bibliography'">
          <div class="section-heading"><div><p class="eyebrow">BIBLIOGRAPHY</p><h2>文章信息</h2></div><button class="button-secondary" type="button" :disabled="readOnly">编辑基础信息</button></div>
          <dl class="workspace-bibliography"><div><dt>标题</dt><dd>{{ workspaceState.workspace.value.bibliography.title }}</dd></div><div><dt>期刊</dt><dd>{{ workspaceState.workspace.value.bibliography.journal }}</dd></div><div><dt>DOI</dt><dd>{{ workspaceState.workspace.value.bibliography.doi || "未报告" }}</dd></div><div><dt>卷 / 期</dt><dd>{{ workspaceState.workspace.value.bibliography.volume }} / {{ workspaceState.workspace.value.bibliography.issue }}</dd></div></dl>
        </template>
        <template v-else-if="activeTab === 'compounds'">
          <CompoundList
            :key="`${workspaceState.workspace.value.id}:${workspaceState.refreshEpoch.value}`"
            :workspace="workspaceState.workspace.value"
            :selected-compound-id="typeof route.query.entity === 'string' ? route.query.entity : undefined"
            :read-only="readOnly"
            @select="selectCompound"
            @mutated="refreshWorkspace"
            @conflict="workspaceState.handleConflict()"
          />
        </template>
        <template v-else-if="activeTab === 'lineages'">
          <LineageEditor
            :key="`${workspaceState.workspace.value.id}:lineages:${workspaceState.refreshEpoch.value}`"
            :workspace="workspaceState.workspace.value"
            :selected-entity-id="typeof route.query.entity === 'string' ? route.query.entity : undefined"
            :read-only="readOnly"
            @select="selectEntity"
            @mutated="refreshWorkspace"
            @conflict="workspaceState.handleConflict()"
          />
        </template>
        <template v-else-if="activeTab === 'evidence'">
          <div class="evidence-activity-workspace">
            <EvidenceEditor
              :key="`${workspaceState.workspace.value.id}:evidence:${workspaceState.refreshEpoch.value}`"
              :workspace="workspaceState.workspace.value"
              :selected-entity-id="typeof route.query.entity === 'string' ? route.query.entity : undefined"
              :read-only="readOnly"
              @select="selectEntity"
              @mutated="refreshWorkspace"
              @conflict="workspaceState.handleConflict()"
            />
            <ActivityEditor
              :key="`${workspaceState.workspace.value.id}:activities:${workspaceState.refreshEpoch.value}`"
              :workspace="workspaceState.workspace.value"
              :selected-entity-id="typeof route.query.entity === 'string' ? route.query.entity : undefined"
              :read-only="readOnly"
              @select="selectEntity"
              @mutated="refreshWorkspace"
              @conflict="workspaceState.handleConflict()"
            />
          </div>
        </template>
        <template v-else>
          <SubmissionChecklist
            :key="`${workspaceState.workspace.value.id}:submission:${workspaceState.refreshEpoch.value}`"
            :workspace="workspaceState.workspace.value"
            :read-only="readOnly"
            @navigate="focusRecord"
            @mutated="refreshWorkspace"
            @conflict="workspaceState.handleConflict()"
          />
        </template>
      </section>
    </template>
  </div>
</template>

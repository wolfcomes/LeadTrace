<script setup lang="ts">
import { t } from "../../i18n";
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { lineageTypeSchema, type LineageType } from "../../v2/types";
import { listActivities, listCompounds, listLineages } from "../../v2/api";

import { useAuthStore } from "../../auth/store";
import { provideReviewProgress } from "./useReviewProgress";
import BibliographyEditor from "./BibliographyEditor.vue";
import { provideHighlights } from "./useHighlights";
import HighlightEditor from "./HighlightEditor.vue";
import ReviewerHelp from "./ReviewerHelp.vue";
import ActivityComparison from "./ActivityComparison.vue";
import CompoundList from "./CompoundList.vue";
import LineageEditor from "./LineageEditor.vue";
import SectionStatusControl from "./SectionStatusControl.vue";
import SubmissionChecklist from "./SubmissionChecklist.vue";
import { usePaperWorkspace } from "./usePaperWorkspace";
import WorkspaceHeader from "./WorkspaceHeader.vue";
import WorkspaceHistory from "./WorkspaceHistory.vue";
import { providePendingEdits } from "./usePendingEdits";

const tabs = [
  { key: "bibliography", label: "文章信息" },
  { key: "compounds", label: "化合物与结构" },
  { key: "activity-comparison", label: "活性对比" },
  { key: "lineages", label: "Lineage" },
  { key: "submit", label: "检查与提交" },
] as const;
type TabKey = typeof tabs[number]["key"];

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const workspaceState = usePaperWorkspace(route, router);
const activeTab = computed<TabKey>(() => {
  const value = route.query.tab;
  if (value === "evidence") return "lineages";
  return tabs.some((tab) => tab.key === value) ? value as TabKey : "bibliography";
});
const canEdit = computed(() => (
  auth.user?.role === "reviewer"
  && workspaceState.workspace.value?.state === "editing"
));
const historyBusy = ref(false);
const historyReloading = ref(false);
const historyEpoch = ref(0);
const pendingEdits = providePendingEdits();
const readOnly = computed(() => !canEdit.value || historyBusy.value || historyReloading.value);
const progress = provideReviewProgress(() => workspaceState.workspace.value ?? undefined, () => canEdit.value);
provideHighlights(() => workspaceState.workspace.value ?? undefined);
const visitedTabs = ref(new Set<string>());
watch(activeTab, tab => visitedTabs.value.add(tab), { immediate: true });

function selectTab(tab: TabKey): void {
  void router.replace({ path: route.path, query: { ...route.query, tab } });
}

function selectCompound(compoundId: string): void {
  void router.replace({ path: route.path, query: { ...route.query, comparison_compound: undefined, entity: compoundId } });
}

async function openComparisonRecord(compoundId: string, activityId?: string): Promise<void> {
  if (pendingEdits.blocked.value || historyBusy.value || historyReloading.value || workspaceState.savingSection.value) return;
  const target = workspaceState.workspace.value;
  if (!target) return;
  // Do not advance an existing draft's version just by reading the comparison.
  // Freeze editing for the whole refresh, including a manual tab switch mid-flight.
  historyReloading.value = true;
  try {
    const latest = await workspaceState.reload(target);
    // Remount previously visited editors so old fields cannot be edited at the
    // freshly loaded version while their individual data requests are pending.
    if (latest?.id === target.id) historyEpoch.value++;
    if (latest?.id === target.id && activeTab.value === 'activity-comparison') {
      await router.push({path: route.path, query: {...route.query, tab: 'compounds', entity: activityId ?? compoundId, comparison_compound: compoundId, from_comparison: '1'}});
    }
  } finally { historyReloading.value = false; }
}

function selectEntity(entityId: string | undefined, group?: LineageType): void {
  const lineageGroup = group ?? route.query.lineage_group;
  if (route.query.entity === entityId && route.query.lineage_group === lineageGroup) return;
  void router.push({ path: route.path, query: { ...route.query, entity: entityId, lineage_group: lineageGroup } });
}

async function focusRecord(tab: "bibliography" | "compounds" | "lineages" | "evidence", entityId?: string): Promise<void> {
  if (tab === "evidence") {
    try { tab = await resolveEvidenceTab(entityId); }
    catch { tab = "lineages"; }
  }
  const { entity: _currentEntity, ...preservedQuery } = route.query;
  const query = { ...preservedQuery, tab, ...(entityId ? { entity: entityId } : {}) };
  void router.replace({ path: route.path, query });
}

async function resolveEvidenceTab(entityId?: string): Promise<"compounds" | "lineages"> {
  const workspace = workspaceState.workspace.value;
  if (!workspace || !entityId) return "lineages";
  const lineageResult = await listLineages(workspace.id);
  if (lineageResult.items.some(lineage => lineage.id === entityId || lineage.edges.some(edge => edge.id === entityId))) return "lineages";
  const compounds = await listCompounds(workspace.id);
  const results = await Promise.all(compounds.items.map(compound => listActivities(compound.id)));
  return results.some(result => result.items.some(activity => activity.id === entityId || activity.evidence_id === entityId)) ? "compounds" : "lineages";
}
watch([() => route.query.tab, () => route.query.entity, () => workspaceState.workspace.value?.id], async () => {
  if (route.query.tab !== "evidence" || !workspaceState.workspace.value) return;
  const entity = route.query.entity;
  const workspaceId = workspaceState.workspace.value.id;
  try {
    const tab = await resolveEvidenceTab(typeof entity === "string" ? entity : undefined);
    if (route.query.tab === "evidence" && route.query.entity === entity && workspaceState.workspace.value?.id === workspaceId) {
      await router.replace({ path: route.path, query: { ...route.query, tab } });
    }
  } catch { /* Keep the evidence library reachable if navigation lookup fails. */ }
});

async function restoreWorkspace(): Promise<void> {
  historyReloading.value = true;
  const target = workspaceState.workspace.value;
  try {
    const latest = await workspaceState.reload(target);
    if (latest && latest.id === target?.id) historyEpoch.value++;
  } finally { historyReloading.value = false; }
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
    <section v-if="workspaceState.state.value === 'loading'" class="page-state" aria-live="polite"><span class="state-spinner" aria-hidden="true"></span><p>{{ t("正在读取 Paper Workspace…") }}</p></section>
    <section v-else-if="workspaceState.state.value === 'not-found'" class="page-state"><span class="state-symbol">404</span><h1>{{ t("未找到分配任务") }}</h1><p>{{ t("请从“我的任务”重新进入。") }}</p></section>
    <section v-else-if="workspaceState.state.value === 'error'" class="page-state" role="alert"><span class="state-symbol is-error">!</span><h1>{{ t("暂时无法读取 Workspace") }}</h1><small v-if="workspaceState.requestId.value">{{ t("请求编号 ·") }}{{ workspaceState.requestId.value }}</small><button class="button-secondary" type="button" @click="workspaceState.open">{{ t("重新加载") }}</button></section>

    <template v-else-if="workspaceState.workspace.value">
      <WorkspaceHeader :workspace="workspaceState.workspace.value" />
      <ReviewerHelp />
      <WorkspaceHistory :workspace-id="workspaceState.workspace.value.id" :version="workspaceState.workspace.value.version" :read-only="!canEdit" :blocked="pendingEdits.blocked.value || !!workspaceState.savingSection.value || historyReloading || progress.busy.value" @busy="historyBusy = $event" @restored="restoreWorkspace" @conflict="restoreWorkspace" />
      <p v-if="progress.error.value" class="inline-feedback is-warning" role="status">{{ t(progress.error.value) }} <button type="button" class="button-quiet" @click="progress.refresh">{{ t('重试') }}</button></p>
      <p v-if="auth.user?.role === 'admin'" class="inline-feedback is-warning" data-admin-readonly>{{ t("Admin 查看模式：此 Workspace 只读。") }}</p>
      <p v-if="workspaceState.concurrencyMessage.value" class="inline-feedback is-warning" data-concurrency-alert role="alert">{{ t(workspaceState.concurrencyMessage.value) }}</p>
      <p v-if="workspaceState.actionError.value" class="inline-feedback is-error" role="alert">{{ t(workspaceState.actionError.value) }}</p>

      <section class="workspace-section-status" :aria-label='t("六个固定区段状态")'>
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
        <button v-for="tab in tabs" :key="tab.key" type="button" data-workspace-tab :data-workspace-tab-key="tab.key" :aria-current="activeTab === tab.key ? 'page' : undefined" @click="selectTab(tab.key)">{{ t(tab.label) }}</button>
      </nav>

      <section v-if="visitedTabs.has('activity-comparison')" v-show="activeTab === 'activity-comparison'" class="workspace-editor-surface panel">
        <ActivityComparison :key="workspaceState.workspace.value.id" :workspace="workspaceState.workspace.value" :active="activeTab === 'activity-comparison'" :blocked="pendingEdits.blocked.value || historyBusy || historyReloading || !!workspaceState.savingSection.value" @open="openComparisonRecord" />
      </section>
      <p v-if="activeTab === 'compounds' && route.query.from_comparison === '1'">
        <button type="button" class="button-secondary" data-return-comparison :disabled="pendingEdits.blocked.value || historyBusy || historyReloading" @click="selectTab('activity-comparison')">{{ t('← 返回活性对比') }}</button>
      </p>

      <section v-show="activeTab !== 'activity-comparison'" :key="`${workspaceState.workspace.value.id}:editors:${historyEpoch}`" class="workspace-editor-surface panel" :inert="historyBusy || historyReloading">
        <div v-if="visitedTabs.has('bibliography')" v-show="activeTab === 'bibliography'">
        <BibliographyEditor :workspace="workspaceState.workspace.value" :read-only="readOnly" @mutated="refreshWorkspace" @conflict="workspaceState.handleConflict()" />
        <HighlightEditor :workspace="workspaceState.workspace.value" :read-only="readOnly" @mutated="refreshWorkspace" @conflict="workspaceState.handleConflict()" />
        </div>
        <div v-if="visitedTabs.has('compounds')" v-show="activeTab === 'compounds'">
          <CompoundList :active="activeTab === 'compounds'"
            :key="`${workspaceState.workspace.value.id}:${workspaceState.refreshEpoch.value}`"
            :workspace="workspaceState.workspace.value"
            :owner-compound-id="typeof route.query.comparison_compound === 'string' ? route.query.comparison_compound : undefined"
            :selected-compound-id="typeof route.query.entity === 'string' ? route.query.entity : undefined"
            :read-only="readOnly"
            @select="selectCompound"
            @mutated="refreshWorkspace"
            @conflict="workspaceState.handleConflict()"
          />
        </div>
        <div v-if="visitedTabs.has('lineages')" v-show="activeTab === 'lineages'">
          <LineageEditor :active="activeTab === 'lineages'"
            :key="`${workspaceState.workspace.value.id}:lineages:${workspaceState.refreshEpoch.value}`"
            :selected-group-type="lineageTypeSchema.safeParse(route.query.lineage_group).data"
            :workspace="workspaceState.workspace.value"
            :selected-entity-id="typeof route.query.entity === 'string' ? route.query.entity : undefined"
            :read-only="readOnly"
            @select="selectEntity"
            @mutated="refreshWorkspace"
            @conflict="workspaceState.handleConflict()"
          />
        </div>
        <template v-if="activeTab === 'submit'">
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

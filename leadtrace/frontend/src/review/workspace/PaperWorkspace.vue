<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import type { AutosaveState } from "../autosave";
import WorkspaceActionBar from "./WorkspaceActionBar.vue";
import WorkspaceContextRail from "./WorkspaceContextRail.vue";
import WorkspaceEvidenceCanvas from "./WorkspaceEvidenceCanvas.vue";
import type { WorkspaceView } from "./useWorkspace";
import { useWorkspace } from "./useWorkspace";

const props = withDefaults(defineProps<{
  changesetId: string;
  saveState?: AutosaveState;
}>(), { saveState: "idle" });

const emit = defineEmits<{
  ready: [];
  unavailable: [];
  "create-region": [payload: Record<string, unknown>];
  "move-region": [payload: Record<string, unknown>];
  "resize-region": [payload: Record<string, unknown>];
}>();

const route = useRoute();
const router = useRouter();
const controller = useWorkspace();
const mobilePrecision = ref(false);
const fallbackView = ref<"scientific" | "diff" | "submit">("scientific");
let mediaQuery: MediaQueryList | undefined;

const tabs: Array<[WorkspaceView, string]> = [
  ["overview", "概览"],
  ["pdf", "PDF 与 Regions"],
  ["molecules", "Molecule Objects"],
  ["ocsr", "OCSR 与 Structures"],
  ["scientific", "科学数据"],
  ["diff", "Diff"],
  ["submit", "提交"],
];

const mutable = computed(() => (
  controller.workspace.value !== undefined
  && ["draft", "revised_draft"].includes(controller.workspace.value.changeset.workflow_state)
));

function queryValue(value: unknown): string | string[] | null | undefined {
  if (typeof value === "string" || value === null || value === undefined) return value;
  if (Array.isArray(value) && value.every((item) => typeof item === "string")) return value;
  return undefined;
}

function currentDeepLink() {
  return {
    view: queryValue(route.query.view),
    page: queryValue(route.query.page),
    region: queryValue(route.query.region),
    object: queryValue(route.query.object),
    proposal: queryValue(route.query.proposal),
  };
}

function syncQuery(): void {
  void router.replace({
    query: {
      ...route.query,
      view: controller.selectedView.value,
      page: controller.selectedPage.value ? String(controller.selectedPage.value) : undefined,
      region: controller.selectedRegionId.value,
      object: controller.selectedVisualObjectId.value,
      proposal: controller.selectedProposalId.value,
    },
  });
}

function selectView(view: WorkspaceView): void {
  controller.selectedView.value = view;
  syncQuery();
}

function selectPage(page: number): void {
  controller.selectedPage.value = page;
  const selectedRegion = controller.selectedRegion.value;
  if (selectedRegion && selectedRegion.page_number !== page) {
    controller.selectedRegionId.value = undefined;
    controller.selectedVisualObjectId.value = undefined;
    controller.selectedProposalId.value = undefined;
  }
  syncQuery();
}

function selectRegion(regionId: string): void {
  const workspace = controller.workspace.value;
  const region = workspace?.regions.find((item) => item.id === regionId);
  if (!workspace || !region) return;
  controller.selectedRegionId.value = region.id;
  controller.selectedPage.value = region.page_number;
  const visual = workspace.visual_objects.find((item) => item.region_id === region.id);
  controller.selectedVisualObjectId.value = visual?.id;
  controller.selectedProposalId.value = workspace.molecule_proposals.find(
    (item) => item.visual_object_id === visual?.id,
  )?.id;
  syncQuery();
}

function selectObject(visualObjectId: string): void {
  controller.selectVisualObject(visualObjectId);
  syncQuery();
}

function adjacent(direction: 1 | -1): void {
  controller.selectAdjacentUnresolved(direction);
  syncQuery();
}

function updateMediaQuery(event: MediaQueryListEvent | MediaQueryList): void {
  mobilePrecision.value = event.matches;
}

watch(() => props.changesetId, (changesetId) => {
  void controller.load(changesetId, currentDeepLink());
}, { immediate: true });

watch(controller.state, (state) => {
  if (state === "ready") emit("ready");
  if (state === "not-found" || state === "error") emit("unavailable");
});

watch(() => route.query, () => {
  if (controller.state.value === "ready") controller.applyDeepLink(currentDeepLink());
}, { deep: true });

onMounted(() => {
  if (typeof window.matchMedia !== "function") return;
  mediaQuery = window.matchMedia("(max-width: 760px)");
  updateMediaQuery(mediaQuery);
  mediaQuery.addEventListener?.("change", updateMediaQuery);
});

onBeforeUnmount(() => {
  mediaQuery?.removeEventListener?.("change", updateMediaQuery);
});
</script>

<template>
  <section v-if="controller.state.value === 'loading'" class="workspace-state page-state" aria-live="polite">
    <span class="state-spinner" aria-hidden="true"></span>
    <p>正在读取 Paper 科学核查范围…</p>
  </section>

  <section
    v-else-if="controller.state.value === 'ready' && controller.workspace.value"
    class="paper-workspace-shell"
    data-paper-workspace
  >
    <nav class="paper-workspace-tabs workspace-toolbar" data-workspace-tabs aria-label="Paper 工作台视图">
      <button
        v-for="[view, label] in tabs"
        :key="view"
        type="button"
        :aria-current="controller.selectedView.value === view ? 'page' : undefined"
        @click="selectView(view)"
      >{{ label }}</button>
    </nav>

    <div class="paper-workspace-grid">
      <WorkspaceContextRail
        :workspace="controller.workspace.value"
        :selected-page="controller.selectedPage.value"
        :selected-visual-object-id="controller.selectedVisualObjectId.value"
        @select-page="selectPage"
        @select-object="selectObject"
        @previous="adjacent(-1)"
        @next="adjacent(1)"
      />

      <main class="workspace-primary">
        <section v-if="controller.selectedView.value === 'overview'" class="workspace-overview panel">
          <p class="eyebrow">PAPER REVIEW OVERVIEW</p>
          <h2>{{ controller.workspace.value.paper.title ?? controller.workspace.value.paper.paper_key }}</h2>
          <p>从左侧选择页面或 molecule object，中央核对来源，右侧完成专用字段编辑。</p>
          <dl>
            <div><dt>核查范围</dt><dd>{{ controller.workspace.value.progress.scope_count }}</dd></div>
            <div><dt>已处理</dt><dd>{{ controller.workspace.value.progress.resolved_count }}</dd></div>
            <div><dt>阻塞项</dt><dd>{{ controller.workspace.value.progress.blocker_count }}</dd></div>
          </dl>
        </section>

        <WorkspaceEvidenceCanvas
          v-else-if="['pdf', 'molecules', 'ocsr'].includes(controller.selectedView.value)"
          :workspace="controller.workspace.value"
          :selected-page="controller.selectedPage.value"
          :selected-region="controller.selectedRegion.value"
          :selected-visual-object="controller.selectedVisualObject.value"
          :selected-proposal="controller.selectedProposal.value"
          :read-only="!mutable || mobilePrecision"
          :desktop-required="mobilePrecision"
          @select-page="selectPage"
          @select-region="selectRegion"
          @create-region="emit('create-region', $event)"
          @move-region="emit('move-region', $event)"
          @resize-region="emit('resize-region', $event)"
        />

        <slot v-else-if="controller.selectedView.value === 'scientific'" name="scientific">
          <section class="workspace-placeholder panel"><h2>科学数据</h2><p>Activity、Evidence 与 Lineage 编辑器将在这里保持同一 Paper 上下文。</p></section>
        </slot>
        <slot v-else-if="controller.selectedView.value === 'diff'" name="diff">
          <section class="workspace-placeholder panel"><h2>Diff</h2><p>当前修改的结构化差异将在这里显示。</p></section>
        </slot>
        <slot v-else name="submit">
          <section class="workspace-placeholder panel"><h2>提交</h2><p>完成所有 blocker 后确认 Paper 核查范围。</p></section>
        </slot>
      </main>

      <aside class="workspace-inspector panel" data-workspace-inspector aria-label="专用编辑器">
        <slot
          name="inspector"
          :workspace="controller.workspace.value"
          :region="controller.selectedRegion.value"
          :visual-object="controller.selectedVisualObject.value"
          :proposal="controller.selectedProposal.value"
          :editable="mutable && !mobilePrecision"
        >
          <header>
            <p class="eyebrow">TYPED INSPECTOR</p>
            <h2>专用编辑器</h2>
          </header>
          <dl class="selection-summary">
            <div data-selected-region><dt>Region</dt><dd>{{ controller.selectedRegion.value?.region_key ?? "未选择" }}</dd></div>
            <div><dt>Object</dt><dd>{{ controller.selectedVisualObject.value?.object_key ?? "未选择" }}</dd></div>
            <div data-selected-proposal><dt>Proposal</dt><dd>{{ controller.selectedProposal.value?.proposal_key ?? "未选择" }}</dd></div>
          </dl>
          <p>Region、Visual Object、OCSR 与 Structure 的类型化字段会按当前选择显示在此处。</p>
        </slot>
      </aside>
    </div>

    <WorkspaceActionBar
      :progress="controller.workspace.value.progress"
      :unresolved-count="controller.unresolvedVisualObjects.value.length"
      :save-state="saveState"
      @previous="adjacent(-1)"
      @next="adjacent(1)"
      @diff="selectView('diff')"
      @submit="selectView('submit')"
    />
  </section>

  <section v-else class="legacy-workspace-fallback" data-legacy-workspace>
    <div class="operation-alert" role="status">
      科学证据投影暂不可用；已切换到兼容修改集视图。
      <small v-if="controller.requestId.value">请求编号 · {{ controller.requestId.value }}</small>
    </div>
    <nav class="workspace-tabs workspace-toolbar" aria-label="修改集视图">
      <button type="button" :aria-current="fallbackView === 'scientific' ? 'page' : undefined" @click="fallbackView = 'scientific'">编辑</button>
      <button type="button" :aria-current="fallbackView === 'diff' ? 'page' : undefined" @click="fallbackView = 'diff'">变更对比</button>
      <button type="button" :aria-current="fallbackView === 'submit' ? 'page' : undefined" @click="fallbackView = 'submit'">提交与审批</button>
    </nav>
    <slot v-if="fallbackView === 'scientific'" name="scientific" />
    <slot v-else-if="fallbackView === 'diff'" name="diff" />
    <slot v-else name="submit" />
  </section>
</template>

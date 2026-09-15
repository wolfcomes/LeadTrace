<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { ApiError } from "../../api/client";
import {
  bindVisualObjectAsset,
  bindVisualObjectCompound,
  bindVisualObjectRegion,
  createRegion,
  createStructure,
  drawStructure,
  duplicateRegion,
  removeVisualObjectBinding,
  setRegionTombstone,
  splitRegion,
  validateStructure,
  updateMoleculeProposal,
  updateRegion,
  updateStructure,
  updateVisualObject,
  updateVisualObjectAssetBinding,
  type DraftMutationContext,
  type MoleculeProposalUpdate,
  type StructureValidationInput,
  type StructureValidationResult,
} from "../api";
import type { AutosaveState } from "../autosave";
import MoleculeProposalInspector from "./MoleculeProposalInspector.vue";
import RegionInspector from "./RegionInspector.vue";
import StructureInspector, { type StructureEditorValue } from "./StructureInspector.vue";
import VisualObjectInspector from "./VisualObjectInspector.vue";
import WorkspaceActionBar from "./WorkspaceActionBar.vue";
import WorkspaceContextRail from "./WorkspaceContextRail.vue";
import WorkspaceEvidenceCanvas from "./WorkspaceEvidenceCanvas.vue";
import type { MoleculeObjectType } from "./types";
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
  "workspace-updated": [version: number];
}>();

const route = useRoute();
const router = useRouter();
const controller = useWorkspace();
const mobilePrecision = ref(false);
const fallbackView = ref<"scientific" | "diff" | "submit">("scientific");
const mutationBusy = ref(false);
const mutationError = ref<{ conflict: boolean; message: string }>();
const scientificBusy = ref(false);
const structureValidation = ref<StructureValidationResult | null>(null);
const drawingAssetId = ref<string>();
const generatedDrawingUrl = ref<string>();
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

const selectedStructure = computed(() => {
  const workspace = controller.workspace.value;
  const structureId = controller.selectedProposal.value?.review.resulting_structure_id;
  if (!workspace || typeof structureId !== "string") return undefined;
  return workspace.structures.find((structure) => structure.id === structureId);
});

const selectedDrawingUrl = computed(() => {
  if (generatedDrawingUrl.value) return generatedDrawingUrl.value;
  const workspace = controller.workspace.value;
  const structure = selectedStructure.value;
  if (!workspace || !structure) return null;
  const assetId = structure.snapshot.drawing_asset_id ?? structure.snapshot.rdkit_drawing_asset_id;
  return typeof assetId === "string"
    ? workspace.assets.find((asset) => asset.id === assetId)?.url ?? null
    : null;
});

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

function mutationContext(): DraftMutationContext | undefined {
  const workspace = controller.workspace.value;
  if (!workspace) return undefined;
  return {
    changeset_id: workspace.changeset.id,
    expected_version: workspace.workspace_version,
  };
}

async function runMutation<Result>(
  mutate: () => Promise<Result>,
  after?: (result: Result) => void,
): Promise<void> {
  if (mutationBusy.value) return;
  mutationBusy.value = true;
  mutationError.value = undefined;
  try {
    const result = await mutate();
    after?.(result);
    await controller.refreshAfterConflict();
  } catch (error) {
    if (error instanceof ApiError && error.code === "REVISION_CONFLICT") {
      mutationError.value = {
        conflict: true,
        message: `版本冲突：服务端版本为 ${String(error.details.current_version ?? "未知")}，请刷新后重新检查。`,
      };
    } else if (error instanceof ApiError && error.status === 422) {
      mutationError.value = { conflict: false, message: "输入未通过服务端校验，请检查字段和关联范围。" };
    } else {
      mutationError.value = { conflict: false, message: "修改未保存，请稍后重试。" };
    }
  } finally {
    mutationBusy.value = false;
  }
}

async function refreshConflict(): Promise<void> {
  mutationError.value = undefined;
  await controller.refreshAfterConflict();
}

function saveRegion(payload: {
  page_number: number;
  bounds: { x0: number; y0: number; x1: number; y1: number };
  rotation: 0 | 90 | 180 | 270;
}): void {
  const workspace = controller.workspace.value;
  const region = controller.selectedRegion.value;
  const context = mutationContext();
  if (!workspace || !region || !context) return;
  void runMutation(() => updateRegion(workspace.paper.id, region.id, { ...context, ...payload }));
}

function updateRegionGeometry(payload: Record<string, unknown>): void {
  const workspace = controller.workspace.value;
  const context = mutationContext();
  const regionId = typeof payload.id === "string" ? payload.id : undefined;
  if (!workspace || !context || !regionId) return;
  const bounds = {
    x0: Number(payload.x0), y0: Number(payload.y0), x1: Number(payload.x1), y1: Number(payload.y1),
  };
  void runMutation(() => updateRegion(workspace.paper.id, regionId, {
    ...context,
    page_number: Number(payload.pageNumber),
    bounds,
    rotation: Number(payload.rotation),
  }));
}

function createDrawnRegion(payload: Record<string, unknown>): void {
  const workspace = controller.workspace.value;
  const context = mutationContext();
  if (!workspace || !context) return;
  const page = Number(payload.pageNumber);
  const prefix = `region-p${page}-`;
  const sequence = workspace.regions.filter((region) => region.region_key.startsWith(prefix)).length + 1;
  void runMutation(() => createRegion(workspace.paper.id, {
    ...context,
    region_key: `${prefix}${sequence}`,
    page_number: page,
    bounds: {
      x0: Number(payload.x0), y0: Number(payload.y0), x1: Number(payload.x1), y1: Number(payload.y1),
    },
    rotation: Number(payload.rotation),
  }), (result) => {
    controller.selectedRegionId.value = result.id;
    controller.selectedPage.value = page;
  });
}

function duplicateSelectedRegion(regionKey: string): void {
  const workspace = controller.workspace.value;
  const region = controller.selectedRegion.value;
  const context = mutationContext();
  if (!workspace || !region || !context) return;
  void runMutation(
    () => duplicateRegion(workspace.paper.id, region.id, { ...context, region_key: regionKey }),
    (result) => { controller.selectedRegionId.value = result.id; },
  );
}

function splitSelectedRegion(payload: {
  first_key: string;
  second_key: string;
  first_bounds: { x0: number; y0: number; x1: number; y1: number };
  second_bounds: { x0: number; y0: number; x1: number; y1: number };
}): void {
  const workspace = controller.workspace.value;
  const region = controller.selectedRegion.value;
  const context = mutationContext();
  if (!workspace || !region || !context) return;
  void runMutation(
    () => splitRegion(workspace.paper.id, region.id, { ...context, ...payload }),
    (result) => { controller.selectedRegionId.value = result.regions[0]?.id; },
  );
}

function toggleSelectedRegion(action: "tombstone" | "restore"): void {
  const workspace = controller.workspace.value;
  const region = controller.selectedRegion.value;
  const context = mutationContext();
  if (!workspace || !region || !context) return;
  void runMutation(() => setRegionTombstone(workspace.paper.id, region.id, action, context));
}

function saveVisualObject(payload: { object_type: MoleculeObjectType; label: string | null }): void {
  const workspace = controller.workspace.value;
  const visual = controller.selectedVisualObject.value;
  const context = mutationContext();
  if (!workspace || !visual || !context) return;
  void runMutation(() => updateVisualObject(workspace.paper.id, visual.id, { ...context, ...payload }));
}

function bindRegion(payload: { region_id: string; role: string }): void {
  const workspace = controller.workspace.value;
  const visual = controller.selectedVisualObject.value;
  const context = mutationContext();
  if (!workspace || !visual || !context) return;
  void runMutation(() => bindVisualObjectRegion(workspace.paper.id, visual.id, { ...context, ...payload }));
}

function bindAsset(payload: { asset_id: string; role: string; is_primary: boolean }): void {
  const workspace = controller.workspace.value;
  const visual = controller.selectedVisualObject.value;
  const context = mutationContext();
  if (!workspace || !visual || !context) return;
  void runMutation(() => bindVisualObjectAsset(workspace.paper.id, visual.id, { ...context, ...payload }));
}

function bindCompound(payload: { compound_id: string; label: string; role: string }): void {
  const workspace = controller.workspace.value;
  const visual = controller.selectedVisualObject.value;
  const context = mutationContext();
  if (!workspace || !visual || !context) return;
  void runMutation(() => bindVisualObjectCompound(workspace.paper.id, visual.id, { ...context, ...payload }));
}

function removeBinding(payload: { kind: "regions" | "assets" | "compounds"; id: string }): void {
  const workspace = controller.workspace.value;
  const visual = controller.selectedVisualObject.value;
  const context = mutationContext();
  if (!workspace || !visual || !context) return;
  void runMutation(() => removeVisualObjectBinding(workspace.paper.id, visual.id, payload.kind, payload.id, context));
}

function setPrimaryAsset(payload: { id: string; role: string }): void {
  const workspace = controller.workspace.value;
  const visual = controller.selectedVisualObject.value;
  const context = mutationContext();
  if (!workspace || !visual || !context) return;
  void runMutation(() => updateVisualObjectAssetBinding(workspace.paper.id, visual.id, payload.id, {
    ...context, role: payload.role, is_primary: true,
  }));
}

function locateSource(regionId: string): void {
  controller.selectedView.value = "pdf";
  selectRegion(regionId);
}

async function validateScientificStructure(payload: StructureValidationInput): Promise<void> {
  const workspace = controller.workspace.value;
  if (!workspace || scientificBusy.value) return;
  scientificBusy.value = true;
  mutationError.value = undefined;
  try {
    structureValidation.value = await validateStructure(workspace.paper.id, payload);
  } catch (error) {
    structureValidation.value = null;
    mutationError.value = {
      conflict: false,
      message: error instanceof ApiError && error.status === 422
        ? "RDKit 校验未通过，请检查 SMILES 与组分选择。"
        : "暂时无法完成 RDKit 校验。",
    };
  } finally {
    scientificBusy.value = false;
  }
}

function decideProposal(payload: Omit<MoleculeProposalUpdate, "changeset_id" | "expected_version">): void {
  const workspace = controller.workspace.value;
  const proposal = controller.selectedProposal.value;
  const context = mutationContext();
  if (!workspace || !proposal || !context) return;
  void runMutation(() => updateMoleculeProposal(workspace.paper.id, proposal.id, {
    ...context,
    ...payload,
  }));
}

async function drawScientificStructure(smiles: string): Promise<void> {
  const workspace = controller.workspace.value;
  if (!workspace || scientificBusy.value) return;
  scientificBusy.value = true;
  mutationError.value = undefined;
  try {
    const drawing = await drawStructure(workspace.paper.id, { smiles, width: 600, height: 420 });
    drawingAssetId.value = drawing.asset_id;
    generatedDrawingUrl.value = `/api/v1/assets/${drawing.asset_id}/content`;
  } catch {
    mutationError.value = { conflict: false, message: "RDKit 图生成失败；SMILES 和校验结果仍会保留。" };
  } finally {
    scientificBusy.value = false;
  }
}

function saveScientificStructure(payload: StructureEditorValue & { compound_id: string; structure_key: string }): void {
  const workspace = controller.workspace.value;
  const context = mutationContext();
  if (!workspace || !context) return;
  const input = {
    ...context,
    compound_id: payload.compound_id,
    structure_key: payload.structure_key,
    smiles: payload.smiles ?? "",
    selected_component_smiles: payload.selectedComponentSmiles,
    experimental_material: payload.experimentalMaterial,
    source_comparison: payload.sourceComparison,
    source_verified: payload.sourceVerified,
    human_confirmed: payload.humanConfirmed,
    structure_state: payload.structureState,
    source: payload.source,
    reason: payload.reason,
    drawing_asset_id: drawingAssetId.value
      ?? (typeof selectedStructure.value?.snapshot.drawing_asset_id === "string"
        ? selectedStructure.value.snapshot.drawing_asset_id
        : null),
  };
  void runMutation(() => selectedStructure.value
    ? updateStructure(workspace.paper.id, selectedStructure.value.id, input)
    : createStructure(workspace.paper.id, input));
}

function updateMediaQuery(event: MediaQueryListEvent | MediaQueryList): void {
  mobilePrecision.value = event.matches;
}

watch(() => props.changesetId, (changesetId) => {
  void controller.load(changesetId, currentDeepLink());
}, { immediate: true });

watch(controller.state, (state) => {
  if (state === "ready") {
    emit("ready");
    if (controller.workspace.value) emit("workspace-updated", controller.workspace.value.workspace_version);
  }
  if (state === "not-found" || state === "error") emit("unavailable");
});

watch(() => route.query, () => {
  if (controller.state.value === "ready") controller.applyDeepLink(currentDeepLink());
}, { deep: true });

watch(() => controller.selectedProposalId.value, () => {
  structureValidation.value = null;
  drawingAssetId.value = undefined;
  generatedDrawingUrl.value = undefined;
});

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
          @create-region="createDrawnRegion($event); emit('create-region', $event)"
          @move-region="updateRegionGeometry($event); emit('move-region', $event)"
          @resize-region="updateRegionGeometry($event); emit('resize-region', $event)"
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
        <div v-if="mutationError" :data-workspace-conflict="mutationError.conflict ? '' : undefined" class="operation-alert" role="alert">
          {{ mutationError.message }}
          <button v-if="mutationError.conflict" class="button-secondary" data-refresh-conflict type="button" @click="refreshConflict">刷新服务端版本</button>
        </div>
        <slot
          name="inspector"
          :workspace="controller.workspace.value"
          :region="controller.selectedRegion.value"
          :visual-object="controller.selectedVisualObject.value"
          :proposal="controller.selectedProposal.value"
          :editable="mutable && !mobilePrecision"
        >
          <RegionInspector
            v-if="controller.selectedView.value === 'pdf' && controller.selectedRegion.value"
            :region="controller.selectedRegion.value"
            :editable="mutable && !mobilePrecision"
            :busy="mutationBusy"
            :linked-object-count="controller.workspace.value.visual_objects.filter((visual) => visual.region_id === controller.selectedRegion.value?.id).length"
            :source-locator-count="controller.workspace.value.source_locators.filter((locator) => locator.region_id === controller.selectedRegion.value?.id).length"
            @save="saveRegion"
            @duplicate="duplicateSelectedRegion"
            @split="splitSelectedRegion"
            @tombstone="toggleSelectedRegion('tombstone')"
            @restore="toggleSelectedRegion('restore')"
          />
          <VisualObjectInspector
            v-else-if="controller.selectedView.value === 'molecules' && controller.selectedVisualObject.value"
            :visual="controller.selectedVisualObject.value"
            :regions="controller.workspace.value.regions.map((region) => ({ id: region.id, label: region.region_key }))"
            :assets="controller.workspace.value.assets.map((asset) => ({ id: asset.id, filename: asset.original_filename }))"
            :editable="mutable && !mobilePrecision"
            :busy="mutationBusy"
            :has-source-locator="controller.workspace.value.source_locators.some((locator) => locator.visual_object_id === controller.selectedVisualObject.value?.id)"
            @save="saveVisualObject"
            @bind-region="bindRegion"
            @bind-asset="bindAsset"
            @bind-compound="bindCompound"
            @remove-binding="removeBinding"
            @set-primary-asset="setPrimaryAsset"
            @locate-source="locateSource"
          />
          <div v-else-if="controller.selectedView.value === 'ocsr' && controller.selectedProposal.value" class="ocsr-inspector-stack">
            <dl class="selection-summary workspace-selection-summary" aria-label="当前 OCSR 选择">
              <div data-selected-region><dt>Region</dt><dd>{{ controller.selectedRegion.value?.region_key ?? "未选择" }}</dd></div>
              <div data-selected-proposal><dt>Proposal</dt><dd>{{ controller.selectedProposal.value.proposal_key }}</dd></div>
            </dl>
            <MoleculeProposalInspector
              :proposal="controller.selectedProposal.value"
              :structures="controller.workspace.value.structures"
              :editable="mutable && !mobilePrecision"
              :busy="mutationBusy || scientificBusy"
              :validation="structureValidation"
              @validate="validateScientificStructure"
              @decision="decideProposal"
              @locate-source="locateSource"
            />
            <StructureInspector
              :structure="selectedStructure"
              :compound-id="typeof controller.selectedProposal.value.review.compound_id === 'string' ? controller.selectedProposal.value.review.compound_id : undefined"
              :editable="mutable && !mobilePrecision"
              :busy="mutationBusy || scientificBusy"
              :validation="structureValidation"
              :drawing-url="selectedDrawingUrl"
              @validate="validateScientificStructure"
              @draw="drawScientificStructure"
              @save="saveScientificStructure"
            />
          </div>
          <template v-else>
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
          </template>
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

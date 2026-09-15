<script setup lang="ts">
import { computed, ref, watch } from "vue";

import PdfReviewCanvas from "../../pdf-viewer/PdfReviewCanvas.vue";
import type { Workspace, WorkspaceMoleculeProposal, WorkspaceRegion, WorkspaceVisualObject } from "./types";

const props = defineProps<{
  workspace: Workspace;
  selectedPage?: number;
  selectedRegion?: WorkspaceRegion;
  selectedVisualObject?: WorkspaceVisualObject;
  selectedProposal?: WorkspaceMoleculeProposal;
  readOnly?: boolean;
  desktopRequired?: boolean;
}>();

const emit = defineEmits<{
  "select-page": [page: number];
  "select-region": [id: string];
  "create-region": [payload: Record<string, unknown>];
  "move-region": [payload: Record<string, unknown>];
  "resize-region": [payload: Record<string, unknown>];
}>();

const mode = ref<"page" | "crop">("page");
const failedCrop = ref(false);
const failedDrawing = ref(false);

watch(() => props.selectedProposal?.id, () => {
  failedCrop.value = false;
  failedDrawing.value = false;
});

const pdfRegions = computed(() => props.workspace.regions.map((region) => ({
  id: region.id,
  regionKey: region.region_key,
  pageNumber: region.page_number,
  ...region.bounds,
  rotation: region.rotation,
})));

const selectedStructure = computed(() => {
  const structureId = props.selectedProposal?.review.resulting_structure_id;
  return typeof structureId === "string"
    ? props.workspace.structures.find((structure) => structure.id === structureId)
    : undefined;
});

const drawingAsset = computed(() => {
  const structure = selectedStructure.value;
  if (!structure) return undefined;
  const drawingId = structure.snapshot.drawing_asset_id ?? structure.snapshot.rdkit_drawing_asset_id;
  if (typeof drawingId === "string") {
    return props.workspace.assets.find((asset) => asset.id === drawingId);
  }
  return props.workspace.assets.find((asset) => asset.category === "rdkit_structure");
});

const machineSmiles = computed(() => {
  const normalized = props.selectedProposal?.machine.normalized_values;
  const raw = props.selectedProposal?.machine.raw_values;
  const value = normalized?.canonical_smiles ?? raw?.raw_smiles;
  return typeof value === "string" ? value : undefined;
});

const pageCount = computed(() => Math.max(1, ...props.workspace.pages.map((page) => page.page_number)));
</script>

<template>
  <section class="workspace-evidence-canvas" data-evidence-canvas aria-label="来源与结构证据">
    <header class="evidence-canvas-toolbar">
      <div>
        <p class="eyebrow">EVIDENCE CANVAS</p>
        <h2>来源证据</h2>
      </div>
      <div class="segmented-control" role="group" aria-label="证据视图">
        <button type="button" data-evidence-mode="page" :aria-pressed="mode === 'page'" @click="mode = 'page'">整页</button>
        <button type="button" data-evidence-mode="crop" :aria-pressed="mode === 'crop'" @click="mode = 'crop'">聚焦 crop</button>
      </div>
    </header>

    <p v-if="desktopRequired" class="precision-notice" data-desktop-required>
      手机端仅提供只读定位；精确 Region 绘制、移动和缩放需要桌面端完成。
    </p>

    <div v-if="mode === 'page'" class="whole-page-evidence">
      <PdfReviewCanvas
        :pdf-url="workspace.document.url"
        :page-count="pageCount"
        :page="selectedPage"
        :regions="pdfRegions"
        :selected-region-id="selectedRegion?.id"
        :read-only="readOnly"
        @page-change="emit('select-page', $event)"
        @select="emit('select-region', $event)"
        @create-region="emit('create-region', $event)"
        @move-region="emit('move-region', $event)"
        @resize-region="emit('resize-region', $event)"
      />
    </div>
    <div v-else class="focused-crop-evidence evidence-preview-frame">
      <img
        v-if="selectedProposal?.crop_asset && !failedCrop"
        data-focused-crop
        :src="selectedProposal.crop_asset.url"
        :alt="`${selectedVisualObject?.object_key ?? '当前对象'} 的聚焦 crop`"
        @error="failedCrop = true"
      >
      <p v-else data-crop-missing>当前对象没有可用的 crop，请先核对来源 Region 与 asset binding。</p>
    </div>

    <section class="evidence-comparison" aria-label="Crop、机器提议与结构图对照">
      <article class="evidence-preview-frame" data-crop-frame>
        <header><strong>Source crop</strong><small>{{ selectedVisualObject?.object_key ?? "未选择对象" }}</small></header>
        <img
          v-if="selectedProposal?.crop_asset && !failedCrop"
          :src="selectedProposal.crop_asset.url"
          :alt="`${selectedVisualObject?.object_key ?? '当前对象'} 的来源 crop`"
          @error="failedCrop = true"
        >
        <p v-else data-crop-missing>当前对象没有可用的 crop。</p>
      </article>
      <article class="evidence-preview-frame machine-proposal-frame">
        <header><strong>Machine proposal</strong><small>{{ selectedProposal?.model_run_key ?? "无 proposal" }}</small></header>
        <code v-if="machineSmiles">{{ machineSmiles }}</code>
        <p v-else>没有可显示的机器 SMILES。</p>
      </article>
      <article class="evidence-preview-frame" data-rdkit-frame>
        <header><strong>Reviewed structure</strong><small>{{ selectedStructure?.state ?? "待确认" }}</small></header>
        <img
          v-if="drawingAsset && !failedDrawing"
          :src="drawingAsset.url"
          :alt="`${selectedStructure?.structure_key ?? '当前结构'} 的 RDKit 图`"
          @error="failedDrawing = true"
        >
        <p v-else data-rdkit-missing>当前对象没有可用的 RDKit 图。</p>
        <code v-if="selectedStructure?.canonical_smiles">{{ selectedStructure.canonical_smiles }}</code>
      </article>
    </section>
  </section>
</template>

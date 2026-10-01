<script setup lang="ts">
import { t } from "../i18n";
import { computed, onMounted, onBeforeUnmount, ref, watch } from "vue";

import { normalizePdfRegionBounds, type PdfRegionBounds } from "./geometry";
import RegionOverlay, { type PdfRegion } from "./RegionOverlay.vue";

const props = withDefaults(defineProps<{
  pdfUrl: string;
  pageCount: number;
  regions: PdfRegion[];
  readOnly?: boolean;
  selectionMode?: boolean;
  allowRotation?: boolean;
  page?: number;
  selectedRegionId?: string;
}>(), { pageCount: 1, allowRotation: true });

type RegionGeometry = PdfRegionBounds & { id: string };

const emit = defineEmits<{
  "create-region": [payload: { pageNumber: number; x0: number; y0: number; x1: number; y1: number; rotation: number }];
  select: [id: string];
  duplicate: [id: string];
  "move-region": [payload: RegionGeometry & { pageNumber: number; rotation: number }];
  "resize-region": [payload: RegionGeometry & { pageNumber: number; rotation: number }];
  "page-change": [page: number];
  "zoom-change": [zoom: number];
  "rotation-change": [rotation: number];
}>();

function clampPage(value: number): number { return Math.min(Math.max(1, props.pageCount), Math.max(1, Number.isFinite(value) ? Math.trunc(value) : 1)); }
const currentPage = ref(clampPage(props.page ?? 1));
const zoom = ref(1);
const rotation = ref(0);
const search = ref("");
const selectedId = ref<string | null>(null);
const drawing = ref<{ x: number; y: number } | null>(null);
const draft = ref<PdfRegionBounds | null>(null);
const canvas = ref<HTMLCanvasElement | null>(null);
const renderedPage = ref(false);
const renderError = ref<string | null>(null);
let generation = 0;
let loadingTask: import("pdfjs-dist").PDFDocumentLoadingTask | null = null;
let documentUrl = "";
let renderTask: import("pdfjs-dist").RenderTask | null = null;
function cancelDrawing(): void { drawing.value = null; draft.value = null; }
function disposeDocument(): void {
  const task = loadingTask;
  loadingTask = null;
  documentUrl = "";
  if (task) void task.destroy().catch(() => {});
}

const pageRegions = computed(() => props.regions.filter((region) => (
  region.pageNumber === currentPage.value
  && (!search.value.trim() || (region.regionKey ?? region.id).toLowerCase().includes(search.value.trim().toLowerCase()))
)));

function point(event: PointerEvent): { x: number; y: number } {
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
  const width = rect.width || 800;
  const height = rect.height || 400;
  return {
    x: Math.min(1, Math.max(0, (event.clientX - rect.left) / width)),
    y: Math.min(1, Math.max(0, (event.clientY - rect.top) / height)),
  };
}

function beginDraw(event: PointerEvent): void {
  if (props.readOnly || !props.selectionMode || !renderedPage.value || rotation.value !== 0) return;
  (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
  drawing.value = point(event);
  draft.value = { x0: drawing.value.x, y0: drawing.value.y, x1: drawing.value.x, y1: drawing.value.y };
}

function updateDraw(event: PointerEvent): void {
  if (!drawing.value) return;
  const end = point(event);
  draft.value = {
    x0: Math.min(drawing.value.x, end.x),
    y0: Math.min(drawing.value.y, end.y),
    x1: Math.max(drawing.value.x, end.x),
    y1: Math.max(drawing.value.y, end.y),
  };
}

function finishDraw(event: PointerEvent): void {
  if (props.readOnly || !props.selectionMode || !renderedPage.value || rotation.value !== 0) return;
  if (!drawing.value || !draft.value) return;
  updateDraw(event);
  const finished = draft.value;
  drawing.value = null;
  draft.value = null;
  if (finished.x1 - finished.x0 < 0.01 || finished.y1 - finished.y0 < 0.01) return;
  const normalized = normalizePdfRegionBounds(finished);
  if (!normalized) return;
  emit("create-region", { pageNumber: currentPage.value, ...normalized, rotation: rotation.value });
}

function changePage(page: number): void {
  currentPage.value = clampPage(page);
  emit("page-change", currentPage.value);
}

function regionGeometry(kind: "move-region" | "resize-region", payload: RegionGeometry): void {
  if (!renderedPage.value || props.readOnly || !props.selectionMode || rotation.value !== 0) return;
  const region = props.regions.find((item) => item.id === payload.id);
  const geometry = {
    ...payload,
    pageNumber: region?.pageNumber ?? currentPage.value,
    rotation: region?.rotation ?? rotation.value,
  };
  if (kind === "move-region") emit("move-region", geometry);
  else emit("resize-region", geometry);
}

function setZoom(value: number): void {
  zoom.value = Math.min(3, Math.max(.5, value));
  emit("zoom-change", zoom.value);
}

function setRotation(value: number): void {
  if (!props.allowRotation) return;
  rotation.value = ((value % 360) + 360) % 360;
  emit("rotation-change", rotation.value);
}

async function renderPdfPage(): Promise<void> {
  const request = ++generation;
  const url = props.pdfUrl, pageNumber = currentPage.value, scale = zoom.value;
  renderedPage.value = false;
  renderError.value = null;
  cancelDrawing();
  renderTask?.cancel();
  renderTask = null;
  if (typeof window === "undefined" || !canvas.value) return;
  try {
    const pdfjs = await import("pdfjs-dist");
    if (request !== generation) return;
    pdfjs.GlobalWorkerOptions.workerSrc = new URL(
      "pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url,
    ).toString();
    if (!loadingTask || documentUrl !== url) {
      disposeDocument();
      documentUrl = url;
      loadingTask = pdfjs.getDocument({ url });
    }
    const document = await loadingTask.promise;
    if (request !== generation) return;
    const page = await document.getPage(pageNumber);
    if (request !== generation) return;
    const viewport = page.getViewport({ scale });
    // Each request renders off screen; a cancelled task cannot paint a newer page.
    const buffer = window.document.createElement("canvas");
    buffer.width = Math.ceil(viewport.width);
    buffer.height = Math.ceil(viewport.height);
    const context = buffer.getContext("2d");
    if (!context) throw new Error("Canvas is unavailable");
    const task = page.render({ canvasContext: context, viewport });
    renderTask = task;
    await task.promise;
    if (request !== generation || !canvas.value) return;
    const visibleContext = canvas.value.getContext("2d");
    if (!visibleContext) throw new Error("Canvas is unavailable");
    canvas.value.width = buffer.width;
    canvas.value.height = buffer.height;
    visibleContext.drawImage(buffer, 0, 0);
    renderTask = null;
    renderedPage.value = true;
  } catch {
    if (request === generation) renderError.value = "PDF 页面暂时无法渲染";
  }
}

watch(() => props.pdfUrl, () => {
  disposeDocument();
  void renderPdfPage();
}, { flush: "sync" });
watch(() => props.page, (page) => {
  if (page !== undefined && page !== currentPage.value) {
    currentPage.value = clampPage(page);
  }
});
watch(() => props.selectedRegionId, (regionId) => {
  if (regionId) selectedId.value = regionId;
}, { immediate: true });
watch([currentPage, zoom], () => { void renderPdfPage(); }, { flush: "sync" });
watch(rotation, cancelDrawing, { flush: "sync" });
watch(() => [props.selectionMode, props.readOnly], cancelDrawing, { flush: "sync" });
watch(() => props.pageCount, () => { currentPage.value = clampPage(currentPage.value); });
onBeforeUnmount(() => { generation++; renderTask?.cancel(); disposeDocument(); });
onMounted(() => { void renderPdfPage(); });
</script>

<template>
  <section class="pdf-review-canvas" :aria-label='t("PDF 区域核查")'>
    <header class="canvas-toolbar workspace-toolbar">
      <label class="form-field">{{ t("页码") }}<input class="form-control" :aria-label='t("页码")' type="number" :min="1" :max="pageCount" :value="currentPage" @change="changePage(Number(($event.target as HTMLInputElement).value))"></label>
      <span>/ {{ pageCount }}</span>
      <button class="button-quiet" type="button" :aria-label='t("上一页")' :disabled="currentPage <= 1" @click="changePage(currentPage - 1)">{{ t("上一页") }}</button>
      <button class="button-quiet" type="button" :aria-label='t("下一页")' :disabled="currentPage >= pageCount" @click="changePage(currentPage + 1)">{{ t("下一页") }}</button>
      <label class="form-field">{{ t("搜索") }}<input v-model="search" class="form-control" type="search" :aria-label='t("区域搜索")'></label>
      <button class="button-quiet" type="button" :aria-label='t("缩小")' :title='t("缩小")' @click="setZoom(zoom - .1)">-</button>
      <output :aria-label='t("缩放")'>{{ Math.round(zoom * 100) }}%</output>
      <button class="button-quiet" type="button" :aria-label='t("放大")' :title='t("放大")' @click="setZoom(zoom + .1)">+</button>
      <button class="button-quiet" type="button" :aria-label='t("旋转")' :disabled="!allowRotation" @click="setRotation(rotation + 90)">{{ t("旋转") }}</button>
    </header>
    <nav class="page-thumbnails" :aria-label='t("页面缩略图")'>
      <button v-for="page in pageCount" :key="page" type="button" :class="['button-quiet', { active: page === currentPage }]" :aria-label="t('第 {p0} 页', { p0: page })" @click="changePage(page)">{{ page }}</button>
    </nav>
    <div class="pdf-page-shell" :class="{ 'is-rendered': renderedPage }">
      <div
        class="pdf-page"
        data-pdf-page
        :data-page-number="currentPage"
        :data-selection-mode="selectionMode && renderedPage && rotation === 0 ? 'true' : 'false'"
        :style="{ transform: `rotate(${rotation}deg)` }"
        @pointerdown="beginDraw"
        @pointermove="updateDraw"
        @pointerup="finishDraw"
        @pointercancel="cancelDrawing"
      >
        <canvas ref="canvas" data-pdf-canvas :aria-label='t("PDF 页面")'></canvas>
        <iframe
          v-if="!renderedPage"
          class="pdf-fallback"
          :src="`${pdfUrl}#page=${currentPage}`"
          :title='t("PDF 页面")'
        ></iframe>
        <p v-if="renderError" class="render-error">{{ t(renderError) }}</p>
        <RegionOverlay
          v-for="region in (renderedPage ? pageRegions : [])"
          :key="region.id"
          :region="region"
          :selected="(selectedRegionId ?? selectedId) === region.id"
          :read-only="readOnly || !selectionMode || rotation !== 0"
          @select="(id) => { selectedId = id; emit('select', id); }"
          @duplicate="(id) => emit('duplicate', id)"
          @move="regionGeometry('move-region', $event)"
          @resize="regionGeometry('resize-region', $event)"
        />
        <div v-if="draft" class="draft-region" :style="{ left: `${draft.x0 * 100}%`, top: `${draft.y0 * 100}%`, width: `${(draft.x1 - draft.x0) * 100}%`, height: `${(draft.y1 - draft.y0) * 100}%` }" />
      </div>
    </div>
  </section>
</template>

<style scoped>
.pdf-review-canvas { display: grid; gap: 12px; color: var(--ink-soft); }
.canvas-toolbar { align-items: flex-end; font-size: 13px; }
.canvas-toolbar .form-control { min-width: 4rem; }
.page-thumbnails { display: flex; gap: 6px; overflow-x: auto; }
.page-thumbnails button.active { border-color: var(--teal); color: white; background: var(--teal); }
.pdf-page-shell { width: 800px; max-width: 100%; transform-origin: top left; }
.pdf-page { position: relative; width: 800px; max-width: 100%; outline: 1px solid var(--line-strong); background-color: var(--surface); touch-action: none; overflow: hidden; }
.pdf-page canvas { display: block; width: 100%; height: auto;  }
.pdf-fallback { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; background: var(--surface); }
.render-error { position: absolute; inset: 12px auto auto 12px; margin: 0; padding: 5px 8px; color: var(--amber-deep); background: color-mix(in srgb, var(--amber-pale) 92%, transparent); font-size: 12px; }
.draft-region { position: absolute; border: 2px dashed var(--coral-deep); background: color-mix(in srgb, var(--coral) 12%, transparent); pointer-events: none; }
</style>

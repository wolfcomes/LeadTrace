<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import RegionOverlay, { type PdfRegion } from "./RegionOverlay.vue";

const props = withDefaults(defineProps<{
  pdfUrl: string;
  pageCount: number;
  regions: PdfRegion[];
  readOnly?: boolean;
  page?: number;
  selectedRegionId?: string;
}>(), { pageCount: 1 });

type RegionGeometry = { id: string; x0: number; y0: number; x1: number; y1: number };

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

const currentPage = ref(Math.min(props.pageCount, Math.max(1, props.page ?? 1)));
const zoom = ref(1);
const rotation = ref(0);
const search = ref("");
const selectedId = ref<string | null>(null);
const drawing = ref<{ x: number; y: number } | null>(null);
const draft = ref<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
const canvas = ref<HTMLCanvasElement | null>(null);
const renderedPage = ref(false);
const renderError = ref<string | null>(null);
let pdfDocument: { getPage: (page: number) => Promise<any> } | null = null;

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
  if (props.readOnly) return;
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
  if (props.readOnly) return;
  if (!drawing.value || !draft.value) return;
  updateDraw(event);
  const finished = draft.value;
  drawing.value = null;
  draft.value = null;
  if (finished.x1 - finished.x0 < 0.01 || finished.y1 - finished.y0 < 0.01) return;
  emit("create-region", { pageNumber: currentPage.value, ...finished, rotation: rotation.value });
}

function changePage(page: number): void {
  currentPage.value = Math.min(props.pageCount, Math.max(1, page));
  emit("page-change", currentPage.value);
}

function regionGeometry(kind: "move-region" | "resize-region", payload: RegionGeometry): void {
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
  rotation.value = ((value % 360) + 360) % 360;
  emit("rotation-change", rotation.value);
}

async function renderPdfPage(): Promise<void> {
  renderedPage.value = false;
  renderError.value = null;
  if (typeof window === "undefined" || !canvas.value) return;
  try {
    const pdfjs = await import("pdfjs-dist");
    pdfjs.GlobalWorkerOptions.workerSrc = new URL(
      "pdfjs-dist/build/pdf.worker.min.mjs",
      import.meta.url,
    ).toString();
    if (!pdfDocument) {
      pdfDocument = await pdfjs.getDocument({ url: props.pdfUrl }).promise;
    }
    const page = await pdfDocument.getPage(currentPage.value);
    const viewport = page.getViewport({ scale: zoom.value });
    const context = canvas.value.getContext("2d");
    if (!context) throw new Error("Canvas is unavailable");
    canvas.value.width = Math.ceil(viewport.width);
    canvas.value.height = Math.ceil(viewport.height);
    await page.render({ canvasContext: context, viewport }).promise;
    renderedPage.value = true;
  } catch {
    // Keep the protected PDF URL visible as a fallback when PDF.js cannot load.
    renderError.value = "PDF 页面暂时无法渲染";
  }
}

watch(() => props.pdfUrl, () => {
  pdfDocument = null;
  void renderPdfPage();
});
watch(() => props.page, (page) => {
  if (page !== undefined && page !== currentPage.value) {
    currentPage.value = Math.min(props.pageCount, Math.max(1, page));
  }
});
watch(() => props.selectedRegionId, (regionId) => {
  if (regionId) selectedId.value = regionId;
}, { immediate: true });
watch([currentPage, zoom], () => { void renderPdfPage(); });
onMounted(() => { void renderPdfPage(); });
</script>

<template>
  <section class="pdf-review-canvas" aria-label="PDF 区域核查">
    <header class="canvas-toolbar workspace-toolbar">
      <label class="form-field">页码 <input class="form-control" aria-label="页码" type="number" :min="1" :max="pageCount" :value="currentPage" @change="changePage(Number(($event.target as HTMLInputElement).value))"></label>
      <span>/ {{ pageCount }}</span>
      <button class="button-quiet" type="button" aria-label="上一页" :disabled="currentPage <= 1" @click="changePage(currentPage - 1)">上一页</button>
      <button class="button-quiet" type="button" aria-label="下一页" :disabled="currentPage >= pageCount" @click="changePage(currentPage + 1)">下一页</button>
      <label class="form-field">搜索 <input v-model="search" class="form-control" type="search" aria-label="区域搜索"></label>
      <button class="button-quiet" type="button" aria-label="缩小" title="缩小" @click="setZoom(zoom - .1)">-</button>
      <output aria-label="缩放">{{ Math.round(zoom * 100) }}%</output>
      <button class="button-quiet" type="button" aria-label="放大" title="放大" @click="setZoom(zoom + .1)">+</button>
      <button class="button-quiet" type="button" aria-label="旋转" @click="setRotation(rotation + 90)">旋转</button>
    </header>
    <nav class="page-thumbnails" aria-label="页面缩略图">
      <button v-for="page in pageCount" :key="page" type="button" :class="['button-quiet', { active: page === currentPage }]" :aria-label="`第 ${page} 页`" @click="changePage(page)">{{ page }}</button>
    </nav>
    <div class="pdf-page-shell" :class="{ 'is-rendered': renderedPage }">
      <div
        class="pdf-page"
        data-pdf-page
        :data-page-number="currentPage"
        :style="{ transform: `rotate(${rotation}deg)` }"
        @pointerdown="beginDraw"
        @pointermove="updateDraw"
        @pointerup="finishDraw"
        @pointercancel="finishDraw"
      >
        <canvas ref="canvas" data-pdf-canvas aria-label="PDF 页面"></canvas>
        <iframe
          v-if="!renderedPage"
          class="pdf-fallback"
          :src="`${pdfUrl}#page=${currentPage}`"
          title="PDF 页面"
        ></iframe>
        <p v-if="renderError" class="render-error">{{ renderError }}</p>
        <RegionOverlay
          v-for="region in pageRegions"
          :key="region.id"
          :region="region"
          :selected="(selectedRegionId ?? selectedId) === region.id"
          :read-only="readOnly"
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
.pdf-page { position: relative; width: 800px; max-width: 100%; min-height: 400px; border: 1px solid var(--line-strong); background-color: var(--surface); touch-action: none; overflow: hidden; }
.pdf-page canvas { display: block; width: 100%; height: auto; min-height: 400px; object-fit: contain; }
.pdf-fallback { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; background: var(--surface); }
.render-error { position: absolute; inset: 12px auto auto 12px; margin: 0; padding: 5px 8px; color: var(--amber-deep); background: color-mix(in srgb, var(--amber-pale) 92%, transparent); font-size: 12px; }
.draft-region { position: absolute; border: 2px dashed var(--coral-deep); background: color-mix(in srgb, var(--coral) 12%, transparent); pointer-events: none; }
</style>

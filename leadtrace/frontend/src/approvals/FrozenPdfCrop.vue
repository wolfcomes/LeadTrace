<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from "vue";
import { t } from "../i18n";
import { cropGeometry, useFrozenPdfPool, type CropBounds } from "./frozenPdf";
import type { RenderTask } from "pdfjs-dist";
const props = defineProps<{
  url: string;
  sha: string;
  page: number;
  bounds: CropBounds;
  eager?: boolean;
  label: string;
}>();
const pool = useFrozenPdfPool(),
  host = ref<HTMLElement>(),
  canvas = ref<HTMLCanvasElement>();
const ready = ref(false),
  error = ref(""),
  visible = ref(false);
let observer: IntersectionObserver | undefined,
  resize: ResizeObserver | undefined,
  generation = 0,
  task: RenderTask | undefined,
  frame = 0,
  width = 0;
async function render() {
  const token = ++generation;
  task?.cancel();
  ready.value = false;
  error.value = "";
  if (!visible.value || !canvas.value) return;
  const requested = {
    url: props.url,
    sha: props.sha,
    page: props.page,
    bounds: { ...props.bounds },
  };
  try {
    await pool.render(async () => {
      if (token !== generation) return;
      const document = await pool.document(requested.url, requested.sha);
      if (token !== generation) return;
      const page = await document.getPage(requested.page);
      if (token !== generation) return;
      const size = page.getViewport({ scale: 1 }),
        geometry = cropGeometry(
          size,
          requested.bounds,
          host.value?.clientWidth || 400,
          window.devicePixelRatio || 1,
        );
      const buffer = window.document.createElement("canvas");
      buffer.width = geometry.width;
      buffer.height = geometry.height;
      const context = buffer.getContext("2d");
      if (!context) throw new Error("canvas");
      const current = page.render({
        canvasContext: context,
        viewport: page.getViewport({ scale: geometry.scale }),
        transform: [1, 0, 0, 1, geometry.offsetX, geometry.offsetY],
      });
      task = current;
      await current.promise;
      if (token !== generation || !canvas.value) return;
      canvas.value.width = buffer.width;
      canvas.value.height = buffer.height;
      canvas.value.getContext("2d")?.drawImage(buffer, 0, 0);
      ready.value = true;
      if (task === current) task = undefined;
    });
  } catch (caught) {
    if (token === generation)
      error.value =
        caught instanceof Error && caught.message === "source-mismatch"
          ? "证据来源与冻结 PDF 不一致，请核对原文版本。"
          : "原文截图暂时无法读取，请重试。";
  }
}
function schedule() {
  cancelAnimationFrame(frame);
  frame = requestAnimationFrame(() => {
    void render();
  });
}
watch(() => [props.url, props.sha, props.page, props.bounds], schedule);
onMounted(() => {
  if (props.eager || typeof IntersectionObserver === "undefined") {
    visible.value = true;
    schedule();
  } else {
    observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          visible.value = true;
          observer?.disconnect();
          schedule();
        }
      },
      { rootMargin: "240px" },
    );
    if (host.value) observer.observe(host.value);
  }
  if (typeof ResizeObserver !== "undefined") {
    resize = new ResizeObserver(() => {
      const next = host.value?.clientWidth || 0;
      if (next && next !== width) {
        width = next;
        schedule();
      }
    });
    if (host.value) resize.observe(host.value);
  }
});
onBeforeUnmount(() => {
  generation++;
  task?.cancel();
  observer?.disconnect();
  resize?.disconnect();
  cancelAnimationFrame(frame);
});
</script>
<template>
  <div ref="host" class="frozen-pdf-crop" :aria-busy="!ready && !error">
    <canvas
      ref="canvas"
      data-evidence-thumbnail
      :data-rendered="ready"
      :aria-label="label"
      role="img"
      v-show="ready"
    />
    <p v-if="error" role="alert">
      {{ t(error) }}
      <button type="button" class="button-quiet" @click="render">
        {{ t("重试") }}
      </button>
    </p>
    <p v-else-if="!ready" class="crop-loading">{{ t("正在读取原文截图…") }}</p>
  </div>
</template>
<style scoped>
.frozen-pdf-crop {
  width: 100%;
  min-height: 96px;
  background: white;
  border: 1px solid var(--line);
  border-radius: 6px;
  overflow: hidden;
}
.frozen-pdf-crop canvas {
  display: block;
  width: 100%;
  height: auto;
}
.frozen-pdf-crop p {
  padding: 1rem;
  font-size: 0.85rem;
  color: var(--ink-muted);
}
</style>

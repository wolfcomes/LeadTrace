<script setup lang="ts">
import cytoscape, { type Core, type StylesheetStyle } from "cytoscape";
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";
import { t, locale } from "../i18n";
import { assetUrl, changeLabels } from "./recordLabels";
import type { FrozenGraph } from "./recordComparison";
export interface GraphViewport {
  zoom: number;
  x: number;
  y: number;
}
const props = defineProps<{
  graph: FrozenGraph;
  side: "before" | "after";
  viewport: GraphViewport;
  selectedId: string;
  structures: boolean;
  unionBounds: { width: number; height: number };
}>();
const emit = defineEmits<{
  viewport: [value: GraphViewport];
  select: [id: string];
  fit: [value: GraphViewport];
}>();
const host = ref<HTMLElement>();
let cy: Core | undefined,
  observer: ResizeObserver | undefined,
  syncing = false,
  disposed = false;
const selector = computed(() => props.selectedId);
function applyViewport() {
  if (!cy) return;
  syncing = true;
  cy.viewport({
    zoom: props.viewport.zoom,
    pan: { x: props.viewport.x, y: props.viewport.y },
  });
  syncing = false;
}
function fit() {
  if (!host.value?.clientWidth || !host.value?.clientHeight) return;
  const width = host.value.clientWidth,
    height = host.value.clientHeight;
  const zoom = Math.min(
    1.3,
    (width - 36) / props.unionBounds.width,
    (height - 36) / props.unionBounds.height,
  );
  emit("fit", {
    zoom,
    x: (width - props.unionBounds.width * zoom) / 2,
    y: (height - props.unionBounds.height * zoom) / 2,
  });
}
function select() {
  cy?.elements().removeClass("selected");
  if (props.selectedId)
    cy?.getElementById(props.selectedId).addClass("selected");
}
function elements() {
  return [
    ...props.graph.nodes.map((n) => ({
      data: {
        id: n.id,
        label: `${n.label}${n.change !== "unchanged" && n.change !== "unknown" ? "\n" + t(changeLabels[n.change]) : ""}`,
        image: n.depiction ? assetUrl(n.depiction) : "",
        change: n.change,
      },
      position: n.position,
    })),
    ...props.graph.edges.map((e) => ({
      data: {
        id: e.id,
        source: e.source,
        target: e.target,
        label: `${e.label}${e.change !== "unchanged" && e.change !== "unknown" ? "\n" + t(changeLabels[e.change]) : ""}`,
        change: e.change,
      },
    })),
  ];
}
function color(name: string) {
  return getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
}
function styles(): StylesheetStyle[] {
  return [
    {
      selector: "node",
      style: {
        "background-color": color("--surface-raised"),
        "border-color": color("--ink-muted"),
        "border-width": 2,
        width: props.structures ? 178 : 88,
        height: props.structures ? 130 : 58,
        shape: "round-rectangle",
        label: "data(label)",
        "text-wrap": "wrap",
        "font-family": color("--font-sans"),
        "font-size": props.structures ? 13 : 12,
        "text-valign": props.structures ? "bottom" : "center",
        "text-margin-y": props.structures ? 8 : 0,
        color: color("--ink"),
      },
    },
    ...(props.structures
      ? [
          {
            selector: 'node[image != ""]',
            style: {
              "background-image": "data(image)",
              "background-fit": "contain",
              "background-width": "90%",
              "background-height": "90%",
            },
          } as StylesheetStyle,
        ]
      : []),
    {
      selector: "edge",
      style: {
        width: 2,
        "line-color": color("--ink-muted"),
        "target-arrow-color": color("--ink-muted"),
        "target-arrow-shape": "triangle",
        "curve-style": "bezier",
        label: "data(label)",
        "font-family": color("--font-sans"),
        "font-size": 10,
        "text-wrap": "wrap",
        "text-background-color": color("--surface-raised"),
        "text-background-opacity": 0.85,
        "text-background-padding": "3px",
        "text-rotation": "autorotate",
        color: color("--ink-soft"),
      },
    },
    {
      selector: '[change = "added"]',
      style: {
        "border-color": color("--teal"),
        "line-color": color("--teal"),
        "target-arrow-color": color("--teal"),
        "border-width": 4,
        width: props.structures ? 178 : 88,
      },
    },
    { selector: 'edge[change = "added"]', style: { width: 4 } },
    {
      selector: '[change = "removed"]',
      style: {
        "border-color": color("--danger"),
        "line-color": color("--danger"),
        "target-arrow-color": color("--danger"),
        "border-style": "dashed",
        "line-style": "dashed",
        "border-width": 3,
      },
    },
    {
      selector: '[change = "modified"], [change = "evidence"]',
      style: {
        "border-color": color("--amber-deep"),
        "line-color": color("--amber-deep"),
        "target-arrow-color": color("--amber-deep"),
        "border-width": 4,
      },
    },
    {
      selector: 'edge[change = "modified"], edge[change = "evidence"]',
      style: { width: 4, "line-style": "dashed" },
    },
    {
      selector: ".selected",
      style: {
        "overlay-color": color("--teal-deep"),
        "overlay-opacity": 0.15,
        "overlay-padding": 8,
        "border-color": color("--teal-deep"),
        "line-color": color("--teal-deep"),
        "target-arrow-color": color("--teal-deep"),
      },
    },
  ];
}
async function render() {
  await nextTick();
  if (document.fonts) {
    await document.fonts.load(
      '13px "Noto Sans SC Variable"',
      "已修改证据更新新增删除",
    );
    await document.fonts.ready;
  }
  if (disposed || !host.value?.clientWidth) return;
  if (!cy) {
    cy = cytoscape({
      container: host.value,
      elements: elements(),
      style: styles(),
      layout: { name: "preset" },
      autoungrabify: true,
      minZoom: 0.08,
      maxZoom: 3,
      wheelSensitivity: 0.2,
    });
    cy.on("tap", "node, edge", (e) => emit("select", e.target.id()));
    cy.on("pan zoom", () => {
      if (!syncing && cy)
        emit("viewport", { zoom: cy.zoom(), x: cy.pan().x, y: cy.pan().y });
    });
    fit();
  } else {
    syncing = true;
    cy.elements().remove();
    cy.add(elements());
    cy.style(styles());
    syncing = false;
  }
  applyViewport();
  select();
}
watch(() => [props.graph, props.structures, locale.value], render, {
  deep: true,
});
watch(() => props.viewport, applyViewport, { deep: true });
watch(selector, select);
onMounted(() => {
  void render();
  if (typeof ResizeObserver !== "undefined") {
    observer = new ResizeObserver(() => {
      cy?.resize();
      if (cy) fit();
      else void render();
    });
    if (host.value) observer.observe(host.value);
  }
});
onBeforeUnmount(() => {
  disposed = true;
  observer?.disconnect();
  cy?.destroy();
});
</script>
<template>
  <section
    class="frozen-graph"
    :data-lineage-graph-side="side"
    :data-node-count="graph.nodes.length"
    :data-edge-count="graph.edges.length"
    :data-selected-id="selectedId"
    :data-zoom="viewport.zoom"
    :data-pan-x="viewport.x"
    :data-pan-y="viewport.y"
  >
    <div
      ref="host"
      class="frozen-graph-canvas"
      :aria-label="
        t(
          side === 'before'
            ? '修改前完整 Lineage 图'
            : '本次提交完整 Lineage 图',
        )
      "
      role="img"
    />
    <p v-if="!graph.nodes.length" class="empty-graph">
      {{ t("此侧无 Lineage 成员。") }}
    </p>
    <div class="graph-local-controls">
      <button
        type="button"
        class="button-quiet"
        @click="
          emit('viewport', {
            ...viewport,
            zoom: Math.min(3, viewport.zoom * 1.25),
          })
        "
        :aria-label="t('放大')"
      >
        ＋</button
      ><button
        type="button"
        class="button-quiet"
        @click="
          emit('viewport', {
            ...viewport,
            zoom: Math.max(0.08, viewport.zoom / 1.25),
          })
        "
        :aria-label="t('缩小')"
      >
        −</button
      ><button type="button" class="button-quiet" data-graph-fit @click="fit">
        {{ t("全图概览") }}
      </button>
    </div>
  </section>
</template>
<style scoped>
.frozen-graph {
  position: relative;
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
}
.frozen-graph-canvas {
  height: 390px;
  width: 100%;
}
.graph-local-controls {
  position: absolute;
  bottom: 0.5rem;
  right: 0.5rem;
  display: flex;
  gap: 0.2rem;
  background: var(--surface-raised);
  border: 1px solid var(--line);
  border-radius: 5px;
}
.empty-graph {
  position: absolute;
  top: 45%;
  width: 100%;
  text-align: center;
  color: var(--ink-muted);
}
.graph-local-controls button {
  padding: 0.3rem 0.5rem;
}
</style>

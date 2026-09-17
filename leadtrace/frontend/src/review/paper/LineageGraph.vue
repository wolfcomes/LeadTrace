<script setup lang="ts">
import cytoscape, { type Core } from "cytoscape";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

import type { Compound, Lineage } from "../../v2/types";

const props = defineProps<{ lineage: Lineage; compounds: Compound[] }>();
const graphElement = ref<HTMLElement | null>(null);
let graph: Core | undefined;

const compoundById = computed(() => new Map(props.compounds.map((compound) => [compound.id, compound])));
const elements = computed(() => [
  ...props.lineage.members.map((member) => ({
    data: {
      id: member.compound_id,
      label: compoundById.value.get(member.compound_id)?.compound_label ?? member.compound_id.slice(0, 8),
      role: member.role,
    },
  })),
  ...props.lineage.edges.map((edge) => ({
    data: {
      id: edge.id,
      source: edge.parent_compound_id,
      target: edge.child_compound_id,
      label: edge.modification_summary || edge.relation_type,
    },
  })),
]);

async function renderGraph(): Promise<void> {
  await nextTick();
  graph?.destroy();
  graph = undefined;
  const container = graphElement.value;
  if (!container || container.clientWidth === 0 || container.clientHeight === 0) return;
  const theme = getComputedStyle(document.documentElement);
  const themeColor = (token: string): string => theme.getPropertyValue(token).trim();
  graph = cytoscape({
    container,
    elements: elements.value,
    autoungrabify: true,
    autounselectify: false,
    boxSelectionEnabled: false,
    userPanningEnabled: true,
    userZoomingEnabled: true,
    layout: { name: "breadthfirst", directed: true, padding: 22, spacingFactor: 1.15 },
    style: [
      {
        selector: "node",
        style: {
          "background-color": themeColor("--teal"),
          color: themeColor("--ink"),
          label: "data(label)",
          "font-size": 11,
          "text-valign": "bottom",
          "text-margin-y": 8,
          width: 34,
          height: 34,
        },
      },
      { selector: "node[role = 'root']", style: { "background-color": themeColor("--coral"), shape: "diamond" } },
      { selector: "node[role = 'terminal']", style: { "background-color": themeColor("--ink-soft"), shape: "round-rectangle" } },
      {
        selector: "edge",
        style: {
          width: 2,
          "line-color": themeColor("--line-strong"),
          "target-arrow-color": themeColor("--line-strong"),
          "target-arrow-shape": "triangle",
          "curve-style": "bezier",
        },
      },
    ],
  });
}

watch(elements, () => { void renderGraph(); }, { deep: true });
onMounted(() => { void renderGraph(); });
onBeforeUnmount(() => graph?.destroy());
</script>

<template>
  <section class="lineage-graph-panel" aria-label="只读 Lineage 图">
    <header><strong>Lineage 图</strong><small>只读；编辑请使用下方 Member / Edge 表单</small></header>
    <div
      ref="graphElement"
      class="lineage-graph"
      data-lineage-graph
      :data-node-count="lineage.members.length"
      :data-edge-count="lineage.edges.length"
      data-read-only="true"
    >
      <p v-if="lineage.members.length === 0">添加 Member 后将在这里显示优化链。</p>
    </div>
  </section>
</template>

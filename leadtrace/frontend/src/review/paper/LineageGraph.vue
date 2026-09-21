<script setup lang="ts">
import cytoscape, { type Core } from 'cytoscape';
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { structureDepictionUrl } from '../../v2/api';
import type { Compound, Lineage } from '../../v2/types';
import type { LineageStructureState } from './useLineageStructures';

const props = defineProps<{ lineage: Lineage; compounds: Compound[]; structures?: Record<string, LineageStructureState>; visible?: boolean }>();
const emit = defineEmits<{ 'select-edge': [edgeId: string] }>();
const graphElement = ref<HTMLElement | null>(null);
const expanded = ref(false);
const mode = ref<'points' | 'structures'>('points');
const isStructureView = computed(() => mode.value === 'structures');
const savedViews = new Map<string, { zoom: number; pan: { x: number; y: number } }>();
let renderedMode = 'points';
let renderedLineageIdentity = '';
const locateId = ref('');
const zoomPercent = ref(100);
const imageCount = ref(0);
let graph: Core | undefined;
let observer: ResizeObserver | undefined;
let renderEpoch = 0;
let renderedIdentity = '';
let disposed = false;
const loadedImages = new Set<string>();
const failedImages = new Set<string>();
const pendingImages = new Map<string, HTMLImageElement>();
const compoundById = computed(() => new Map(props.compounds.map(c => [c.id, c])));
const members = computed(() => props.lineage.members.map(m => ({ ...m, label: compoundById.value.get(m.compound_id)?.compound_label || '?' })));
const lineageIdentity = computed(() => JSON.stringify([props.lineage.id, members.value, props.lineage.edges.map(e => [e.id, e.parent_compound_id, e.child_compound_id, e.relation_type])]));

const graphIdentity = computed(() => `${lineageIdentity.value}:${mode.value}`);

function readableView(): void {
  if (!graph?.nodes().length) return;
  graph.resize(); graph.fit(undefined, 45);
  const zoom = isStructureView.value ? Math.min(1, Math.max(.65, graph.zoom())) : Math.min(1.5, graph.zoom());
  graph.zoom(zoom);
  const roots = graph.nodes('[role = "root"]');
  graph.center(isStructureView.value && roots.length === 1 ? roots : graph.nodes());
}
function fitAll(): void { graph?.resize(); graph?.fit(undefined, 40); }
function zoomBy(factor: number): void {
  if (!graph) return;
  graph.zoom({ level: Math.min(2.5, Math.max(.12, graph.zoom() * factor)), renderedPosition: { x: graph.width() / 2, y: graph.height() / 2 } });
}
function locate(): void {
  if (!graph || !locateId.value) return;
  const node = graph.getElementById(locateId.value);
  graph.elements().removeClass('focused'); node.addClass('focused'); node.connectedEdges().addClass('focused');
  graph.zoom(Math.max(.85, graph.zoom())); graph.center(node);
}
async function toggleExpanded(): Promise<void> {
  expanded.value = !expanded.value; await nextTick(); graph?.resize();
}
function updateImages(): void {
  const current = graph;
  if (!current || disposed || !isStructureView.value) return;
  imageCount.value = 0;
  current.batch(() => {
    for (const member of members.value) {
      const id = member.compound_id;
      const node = current.getElementById(id);
      const state = props.structures?.[id];
      const key = `${id}:${state?.structure?.depiction_asset_id || ''}`;
      const url = structureDepictionUrl(id);
      if (state?.structure?.depiction_asset_id && loadedImages.has(key)) {
        node.data({ image: url, label: member.label }); imageCount.value++;
      } else {
        node.removeData('image');
        node.data('label', `${member.label}\n${state?.status === 'error' || failedImages.has(key) ? '结构图片暂不可用' : !state || state.status === 'loading' || state.structure?.depiction_asset_id ? '结构载入中' : '暂无结构图'}`);
        if (state?.structure?.depiction_asset_id && !failedImages.has(key) && !pendingImages.has(key)) {
          const img = new Image(); pendingImages.set(key, img);
          img.onload = () => { pendingImages.delete(key); if (disposed) return; loadedImages.add(key); updateImages(); };
          img.onerror = () => { pendingImages.delete(key); if (disposed) return; failedImages.add(key); updateImages(); };
          img.src = url;
        }
      }
    }
  });
}
async function renderGraph(): Promise<void> {
  const epoch = ++renderEpoch;
  await nextTick();
  if (disposed || epoch !== renderEpoch) return;
  const container = graphElement.value;
  if (!container || !container.clientWidth || !container.clientHeight) return;
  if (graph && renderedLineageIdentity === lineageIdentity.value) {
    savedViews.set(renderedMode, { zoom: graph.zoom(), pan: { ...graph.pan() } });
  } else { savedViews.clear(); }
  graph?.destroy();
  imageCount.value = 0;
  locateId.value = '';
  const theme = getComputedStyle(document.documentElement);
  const color = (token: string) => theme.getPropertyValue(token).trim();
  graph = cytoscape({
    container,
    elements: [
      ...members.value.map((m, index) => ({ data: { id: m.compound_id, label: m.label, role: m.role }, position: { x: (index % 4) * 320, y: Math.floor(index / 4) * 240 } })),
      ...props.lineage.edges.map(e => ({ data: { id: e.id, source: e.parent_compound_id, target: e.child_compound_id } })),
    ],
    autoungrabify: true, boxSelectionEnabled: false, minZoom: .12, maxZoom: 2.5,
    wheelSensitivity: 3, layout: { name: 'preset' },
    style: [
      { selector: 'node', style: { shape: isStructureView.value ? 'round-rectangle' : 'ellipse', width: isStructureView.value ? 220 : 42, height: isStructureView.value ? 160 : 42,
        'background-color': color(isStructureView.value ? '--surface-raised' : '--teal-pale'), 'border-width': 2, 'border-color': color('--line-strong'),
        label: 'data(label)', color: color('--ink'), 'font-size': isStructureView.value ? 16 : 14, 'font-weight': 600,
        'text-wrap': 'wrap', 'text-max-width': '200px', 'text-valign': 'center', 'text-halign': 'center',
      } },
      { selector: 'node[image]', style: { 'background-image': 'data(image)', 'background-fit': 'contain',
        'background-width': '94%', 'background-height': '88%', 'background-image-crossorigin': 'use-credentials',
        'text-valign': 'bottom', 'text-margin-y': 8,
      } },
      { selector: 'node[role = "root"]', style: { 'border-color': color('--coral'), 'border-width': 4, 'background-color': color(isStructureView.value ? '--surface-raised' : '--coral-pale') } },
      { selector: 'edge', style: { width: 2.5, 'line-color': color('--ink-muted'), 'target-arrow-color': color('--ink-muted'),
        'target-arrow-shape': 'triangle', 'arrow-scale': 1.5, 'curve-style': 'bezier', 'overlay-padding': 14,
      } },
      { selector: 'edge.focused, edge:selected', style: { width: 4, 'line-color': color('--teal'), 'target-arrow-color': color('--teal') } },
      { selector: 'node.focused', style: { 'border-width': 5, 'border-color': color('--teal') } },
    ],
  });
  renderedIdentity = graphIdentity.value;
  renderedLineageIdentity = lineageIdentity.value;
  renderedMode = mode.value;
  const current = graph;
  current.on('tap', 'edge', event => emit('select-edge', event.target.id()));
  current.on('mouseover', 'edge', () => { container.style.cursor = 'pointer'; });
  current.on('mouseout', 'edge', () => { container.style.cursor = ''; });
  current.on('zoom', () => { zoomPercent.value = Math.round(current.zoom() * 100); });
  // Baseline-comparison stars get one clean ring, keeping unrelated branches
  // from lining up behind one another. Other lineages use a spaced force layout.
  const hub = current.nodes().filter(node => current.edges().length === current.nodes().length - 1
    && node.outdegree() === current.edges().length && current.nodes().length > 2).first();
  if (hub.length) {
    current.layout({ name: 'concentric', animate: false, fit: false, avoidOverlap: true,
      nodeDimensionsIncludeLabels: true, minNodeSpacing: isStructureView.value ? 100 : 40,
      concentric: node => node.id() === hub.id() ? 1 : 0, levelWidth: () => 1,
      startAngle: -Math.PI / 2,
    }).run();
  } else {
    current.layout({ name: 'cose', animate: false, randomize: false, fit: false,
      nodeDimensionsIncludeLabels: true, nodeRepulsion: () => isStructureView.value ? 80000 : 6000, idealEdgeLength: () => isStructureView.value ? 100 : 80,
      nodeOverlap: 60, componentSpacing: isStructureView.value ? 100 : 60, numIter: 700, padding: 40,
    }).run();
  }
  const savedView = savedViews.get(mode.value);
  if (savedView) { current.zoom(savedView.zoom); current.pan(savedView.pan); } else readableView();
  updateImages();
}
watch(graphIdentity, () => { void renderGraph(); });
watch(() => props.structures, updateImages, { deep: true });
watch(() => props.visible, async visible => {
  if (visible === false) return;
  await nextTick();
  if (graph && renderedIdentity === graphIdentity.value) graph.resize(); else void renderGraph();
});
onMounted(() => {
  void renderGraph();
  if (typeof ResizeObserver !== 'undefined' && graphElement.value) {
    observer = new ResizeObserver(() => {
      if (!graphElement.value?.clientWidth || !graphElement.value.clientHeight) return;
      if (graph && renderedIdentity === graphIdentity.value) graph.resize(); else void renderGraph();
    }); observer.observe(graphElement.value);
  }
});
onBeforeUnmount(() => {
  disposed = true; renderEpoch++; observer?.disconnect(); graph?.destroy();
  pendingImages.forEach(img => { img.onload = null; img.onerror = null; }); pendingImages.clear();
});
</script>
<template>
  <section class="lineage-graph-panel molecular-lineage-graph" :class="{ expanded }" aria-label="Lineage 交互关系图">
    <header><strong>{{ isStructureView ? '分子结构关系图' : '化合物关系图' }}</strong><small v-if="isStructureView" data-structure-count>已显示 {{ imageCount }} / {{ lineage.members.length }} 幅结构 · {{ lineage.edges.length }} 条关系</small><small v-else>{{ lineage.members.length }} 个化合物 · {{ lineage.edges.length }} 条关系</small></header>
    <div class="lineage-view-switch" role="group" aria-label="关系图显示方式">
      <button type="button" class="button-secondary" data-graph-mode="points" :aria-pressed="mode === 'points'" @click="mode = 'points'">点线图</button>
      <button type="button" class="button-secondary" data-graph-mode="structures" :aria-pressed="mode === 'structures'" @click="mode = 'structures'">结构图</button>
    </div>
    <div class="lineage-graph-toolbar" aria-label="关系图工具">
      <button type="button" class="button-secondary" data-graph-fit @click="fitAll">全图概览</button>
      <button type="button" class="button-secondary" data-graph-readable @click="readableView">{{ isStructureView ? '结构阅读' : '重置视图' }}</button>
      <button type="button" class="button-quiet" aria-label="放大关系图" @click="zoomBy(1.5)">＋</button>
      <span data-graph-zoom>{{ zoomPercent }}%</span>
      <button type="button" class="button-quiet" aria-label="缩小关系图" @click="zoomBy(1 / 1.5)">−</button>
      <button type="button" class="button-quiet" data-graph-expand @click="toggleExpanded">{{ expanded ? '收起画布' : '展开画布' }}</button>
      <label class="graph-compound-locator">定位化合物<select v-model="locateId" data-graph-locate @change="locate"><option value="">选择编号</option><option v-for="member in members" :key="member.compound_id" :value="member.compound_id">{{ member.label }}</option></select></label>
    </div>
    <p class="graph-help">拖动画布或滚轮缩放；点击连线查看关系详情。橙色边框为 Root，箭头含义以关系说明为准。大系列可用“全图概览”定位，再放大阅读结构。</p>
    <div ref="graphElement" class="lineage-graph" data-lineage-graph :data-display-mode="mode" :data-node-count="lineage.members.length" :data-edge-count="lineage.edges.length" data-read-only="true">
      <p v-if="!lineage.members.length">添加 Member 后将在这里显示结构关系图。</p>
    </div>
  </section>
</template>

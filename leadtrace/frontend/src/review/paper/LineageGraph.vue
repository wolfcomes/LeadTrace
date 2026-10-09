<script setup lang="ts">
import { useHighlights } from "./useHighlights";
import { highlightRole } from "../../v2/highlights";
import HighlightBadges from "./HighlightBadges.vue";
import { t, locale } from "../../i18n";
import cytoscape, { type Core, type NodeSingular } from 'cytoscape';
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useAuthStore } from '../../auth/store';
import { getGraphLayout, saveGraphLayout, type GraphLayout } from '../../v2/workbench';
import { structureDepictionUrl } from '../../v2/api';
import type { Compound, Lineage } from '../../v2/types';
import type { LineageStructureState } from './useLineageStructures';

const props = defineProps<{ lineage: Lineage; compounds: Compound[]; structures?: Record<string, LineageStructureState>; visible?: boolean; readOnly?: boolean }>();
const emit = defineEmits<{ 'select-edge': [edgeId: string]; 'select-node': [compoundId: string]; 'add-node': []; connect: [parent: string, child: string] }>();
const auth = useAuthStore();
const connecting = ref(false), parentNode = ref(''), bendEdges = ref(false);
const savingLayout = ref(false), layoutMessage = ref(''), layoutDirty = ref(false);
const layouts = new Map<string, GraphLayout>();
const dirtyLayouts = new Set<string>();
let renderedKey = '';
const layoutKey = () => `${props.lineage.id}:${mode.value}`;
function captureLayout(): void {
  if (!graph || !renderedKey) return;
  const saved = layouts.get(renderedKey);
  if (saved) saved.positions = Object.fromEntries(graph.nodes().filter(n => !n.data('handle')).map(n => [n.id(), {...(n as NodeSingular).position()}]));
}
function markLayoutDirty(): void {
  if (props.readOnly) return;
  captureLayout(); dirtyLayouts.add(renderedKey); layoutDirty.value = true; layoutMessage.value = '';
}
async function persistLayout(): Promise<void> {
  if (props.readOnly || savingLayout.value) return;
  captureLayout(); const key = renderedKey, value = layouts.get(key); if (!value) return;
  const edgeIds = new Set(props.lineage.edges.map(x => x.id));
  value.edge_controls = Object.fromEntries(Object.entries(value.edge_controls).filter(([id]) => edgeIds.has(id)));
  savingLayout.value = true; graph?.autoungrabify(true);
  try {
    const result = await saveGraphLayout(props.lineage.id, value, auth.csrfToken);
    layouts.set(key, result); dirtyLayouts.delete(key); layoutDirty.value = dirtyLayouts.has(renderedKey);
    layoutMessage.value = '布局已保存';
  } catch { layoutMessage.value = '布局未保存，可能已被其他窗口修改；请重新载入布局后重试。'; }
  finally { savingLayout.value = false; graph?.autoungrabify(Boolean(props.readOnly)); }
}
async function reloadLayout(): Promise<void> {
  try {
    const key = layoutKey(), value = await getGraphLayout(props.lineage.id, mode.value);
    if (key !== layoutKey()) return;
    layouts.set(key, value); dirtyLayouts.delete(key); renderedKey = ''; layoutMessage.value = ''; await renderGraph();
  } catch { layoutMessage.value = '布局读取失败，请重试。'; }
}
function handlePositions(): void {
  if (!graph) return;
  const saved = layouts.get(renderedKey);
  for (const edge of graph.edges()) {
    const ctl = saved?.edge_controls[edge.id()] ?? { distance: 0, weight: .5 };
    edge.data({ bend: ctl.distance, weight: ctl.weight });
    const a = edge.source().position(), b = edge.target().position();
    const dx = b.x-a.x, dy = b.y-a.y, len = Math.hypot(dx,dy) || 1;
    const pos = { x: a.x+dx*ctl.weight-dy/len*ctl.distance, y: a.y+dy*ctl.weight+dx/len*ctl.distance };
    const id = 'bend-' + edge.id(), existing = graph.getElementById(id);
    if (bendEdges.value && !props.readOnly) {
      if (existing.length) existing.position(pos);
      else graph.add({ data: { id, handle: true, edgeId: edge.id() }, position: pos });
    } else if (existing.length) existing.remove();
  }
}
function cancelConnect(): void { connecting.value = false; parentNode.value = ''; }
function resetLayout(): void {
  if (props.readOnly || !graph) return;
  graph.nodes('[handle]').remove();
  graph.layout({ name: 'grid', fit: true, avoidOverlap: true, spacingFactor: 1.5 }).run();
  const saved = layouts.get(renderedKey); if (saved) saved.edge_controls = {};
  markLayoutDirty(); handlePositions();
}
watch(bendEdges, handlePositions);
watch(() => props.readOnly, value => { if (value) { cancelConnect(); bendEdges.value = false; graph?.autoungrabify(true); } else graph?.autoungrabify(false); });
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
const highlights = useHighlights();
function highlightedLabel(id: string, label: string): string {
  const entries = highlights?.items.value.filter(x => x.compound_id === id) ?? [];
  return label + entries.map(x => '\n' + t(highlightRole(x.role)) + (x.review_status === 'reviewer_confirmed' ? '' : ' ?')).join('');
}
const compoundById = computed(() => new Map(props.compounds.map(c => [c.id, c])));
const members = computed(() => props.lineage.members.map(m => ({ ...m, label: highlightedLabel(m.compound_id, compoundById.value.get(m.compound_id)?.compound_label || '?') })));
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
      const url = structureDepictionUrl(id, state?.structure?.depiction_asset_id);
      if (state?.structure?.depiction_asset_id && loadedImages.has(key)) {
        node.data({ image: url, label: member.label }); imageCount.value++;
      } else {
        node.removeData('image');
        node.data('label', `${member.label}\n${state?.status === 'error' || failedImages.has(key) ? t('结构图片暂不可用') : !state || state.status === 'loading' || state.structure?.depiction_asset_id ? t('结构载入中') : t('暂无结构图')}`);
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
  captureLayout();
  const key = layoutKey();
  if (!layouts.has(key)) {
    const requestedMode = mode.value;
    try { layouts.set(key, await getGraphLayout(props.lineage.id, requestedMode)); }
    catch { layouts.set(key, { revision: 0, mode: requestedMode, positions: {}, edge_controls: {} }); layoutMessage.value = '布局读取失败，请重试。'; }
    if (disposed || epoch !== renderEpoch) return;
  }
  const stored = layouts.get(key)!;
  layoutDirty.value = dirtyLayouts.has(key);
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
      ...props.lineage.edges.map(e => ({ data: { id: e.id, source: e.parent_compound_id, target: e.child_compound_id, bend: 0, weight: .5 } })),
    ],
    autoungrabify: Boolean(props.readOnly), boxSelectionEnabled: false, minZoom: .12, maxZoom: 2.5,
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
        'target-arrow-shape': 'triangle', 'arrow-scale': 1.5, 'curve-style': 'unbundled-bezier', 'control-point-distances': 'data(bend)', 'control-point-weights': 'data(weight)', 'overlay-padding': 14,
      } },
      { selector: 'edge.focused, edge:selected', style: { width: 4, 'line-color': color('--teal'), 'target-arrow-color': color('--teal') } },
      { selector: 'node[handle]', style: { shape: 'diamond', width: 16, height: 16, label: '', 'background-color': color('--teal'), 'border-width': 1 } },
      { selector: 'node[role = "intermediate"]', style: { 'border-style': 'dashed' } },
      { selector: 'node[role = "terminal"]', style: { 'border-color': color('--teal'), 'border-width': 4 } },
      { selector: 'node.focused', style: { 'border-width': 5, 'border-color': color('--teal') } },
    ],
  });
  renderedIdentity = graphIdentity.value;
  renderedLineageIdentity = lineageIdentity.value;
  renderedMode = mode.value;
  const current = graph;
  renderedKey = key;
  current.on('tap', 'edge', event => { if (!bendEdges.value && !connecting.value) emit('select-edge', event.target.id()); });
  current.on('tap', 'node', event => {
    const node = event.target; if (node.data('handle')) return;
    if (connecting.value && !props.readOnly) {
      if (!parentNode.value) { parentNode.value = node.id(); node.addClass('focused'); }
      else if (parentNode.value !== node.id()) { emit('connect', parentNode.value, node.id()); cancelConnect(); current.nodes().removeClass('focused'); }
    } else emit('select-node', node.id());
  });
  current.on('drag', 'node', event => {
    const node = event.target;
    if (node.data('handle')) {
      const edge = current.getElementById(node.data('edgeId'));
      const a = edge.source().position(), b = edge.target().position(), pos = node.position();
      const dx = b.x-a.x, dy = b.y-a.y, len = Math.hypot(dx,dy) || 1;
      const control = { weight: Math.max(.05,Math.min(.95,((pos.x-a.x)*dx+(pos.y-a.y)*dy)/(len*len))), distance: Math.max(-10000,Math.min(10000,((pos.x-a.x)*-dy+(pos.y-a.y)*dx)/len)) };
      const saved = layouts.get(renderedKey); if (saved) saved.edge_controls[edge.id()] = control;
      edge.data({ bend: control.distance, weight: control.weight });
    } else handlePositions();
  });
  current.on('dragfree', 'node', () => { markLayoutDirty(); handlePositions(); });
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
  for (const node of current.nodes()) if (stored.positions[node.id()]) node.position(stored.positions[node.id()]);
  handlePositions();
  const savedView = savedViews.get(mode.value);
  if (savedView) { current.zoom(savedView.zoom); current.pan(savedView.pan); } else readableView();
  updateImages();
}
// Refresh only localized node text; preserve positions, viewport and selection.
watch(locale, updateImages);
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
  <section @keydown.esc="cancelConnect" class="lineage-graph-panel molecular-lineage-graph" :class="{ expanded }" :aria-label='t("Lineage 交互关系图")'>
    <header><strong>{{ isStructureView ? t("分子结构关系图") : t("化合物关系图") }}</strong><small v-if="isStructureView" data-structure-count>{{ t("已显示 {count} / {total} 幅结构 · {edges} 条关系", { count: imageCount, total: lineage.members.length, edges: lineage.edges.length }) }}</small><small v-else>{{ t("{count} 个化合物 · {edges} 条关系", { count: lineage.members.length, edges: lineage.edges.length }) }}</small></header>
    <div class="lineage-view-switch" role="group" :aria-label='t("关系图显示方式")'>
      <button type="button" class="button-secondary" data-graph-mode="points" :disabled="savingLayout" :aria-pressed="mode === 'points'" @click="mode = 'points'">{{ t("点线图") }}</button>
      <button type="button" class="button-secondary" data-graph-mode="structures" :disabled="savingLayout" :aria-pressed="mode === 'structures'" @click="mode = 'structures'">{{ t("结构图") }}</button>
    </div>
    <div class="lineage-graph-toolbar" :aria-label='t("关系图工具")'>
      <button type="button" class="button-secondary" data-graph-fit @click="fitAll">{{ t("全图概览") }}</button>
      <button type="button" class="button-secondary" data-graph-readable @click="readableView">{{ isStructureView ? t("结构阅读") : t("重置视图") }}</button>
      <button type="button" class="button-quiet" :aria-label='t("放大关系图")' @click="zoomBy(1.5)">＋</button>
      <span data-graph-zoom>{{ zoomPercent }}%</span>
      <button type="button" class="button-quiet" :aria-label='t("缩小关系图")' @click="zoomBy(1 / 1.5)">−</button>
      <button type="button" class="button-quiet" data-graph-expand @click="toggleExpanded">{{ expanded ? t("收起画布") : t("展开画布") }}</button>
      <label class="graph-compound-locator">{{ t("定位化合物") }}<select v-model="locateId" data-graph-locate @change="locate"><option value="">{{ t("选择编号") }}</option><option v-for="member in members" :key="member.compound_id" :value="member.compound_id">{{ member.label }}</option></select></label>
    </div>
    <div v-if="!readOnly" class="lineage-graph-toolbar" data-graph-edit-toolbar>
      <button type="button" class="button-primary" data-graph-add-node @click="emit('add-node')">{{ t('新增 Node') }}</button>
      <button type="button" class="button-secondary" data-graph-add-edge :aria-pressed="connecting" @click="connecting ? cancelConnect() : (connecting = true)">{{ connecting ? t('取消连线') : t('新增 Edge') }}</button>
      <button type="button" class="button-secondary" data-graph-bend :aria-pressed="bendEdges" @click="bendEdges = !bendEdges">{{ t('调整边曲线') }}</button>
      <button type="button" class="button-secondary" data-graph-save-layout :disabled="savingLayout || !layoutDirty" @click="persistLayout">{{ t('保存布局') }}</button>
      <button type="button" class="button-quiet" :disabled="savingLayout" @click="reloadLayout">{{ t('重新载入布局') }}</button>
      <button type="button" class="button-quiet" :disabled="savingLayout" @click="resetLayout">{{ t('重排为网格') }}</button>
      <span v-if="layoutDirty">{{ t('布局尚未保存') }}</span>
    </div>
    <p v-if="connecting" role="status">{{ parentNode ? t('再选择终点 Compound；Esc 取消。') : t('先选择起点 Compound；Esc 取消。') }}</p>
    <p v-if="layoutMessage" role="status">{{ t(layoutMessage) }}</p>
    <p v-if="!readOnly" class="graph-help">{{ t('拖动节点调整位置；开启“调整边曲线”后拖动菱形控制点。完成后保存布局。布局不改变科学关系。') }}</p>
    <p class="graph-help">{{ t("拖动画布或滚轮缩放；点击连线查看关系详情。橙色边框为 Root，箭头含义以关系说明为准。大系列可用“全图概览”定位，再放大阅读结构。") }}</p>
    <div ref="graphElement" class="lineage-graph" data-lineage-graph :data-display-mode="mode" :data-node-count="lineage.members.length" :data-edge-count="lineage.edges.length" :data-read-only="readOnly ? 'true' : 'false'">
      <p v-if="!lineage.members.length">{{ t("添加 Member 后将在这里显示结构关系图。") }}</p>
    </div>
    <details v-if="highlights?.items.value.some(x => lineage.members.some(m => m.compound_id === x.compound_id))" class="graph-highlight-details"><summary>{{ t('文章级分子标注') }}</summary><div v-for="m in lineage.members.filter(m => highlights?.items.value.some(x => x.compound_id === m.compound_id))" :key="m.compound_id"><strong>Compound {{ compoundById.get(m.compound_id)?.compound_label }}</strong><HighlightBadges :compound-id="m.compound_id" /></div></details>
  </section>
</template>

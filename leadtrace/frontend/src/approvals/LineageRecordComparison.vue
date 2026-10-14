<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { t } from "../i18n";
import type { Row } from "./comparison";
import { compoundLabel } from "./comparison";
import {
  lineageGraphPair,
  type PairedRecord,
  type LineageRecord,
} from "./recordComparison";
import { changeLabels, reviewState } from "./recordLabels";
import FrozenLineageGraph, {
  type GraphViewport,
} from "./FrozenLineageGraph.vue";
import { useModalFocus } from "./useModalFocus";
import { useReviewFocus } from "./reviewFocus";
import ReviewFields from "./ReviewFields.vue";
import ReviewDisclosure from "./ReviewDisclosure.vue";
import FrozenEvidence from "./FrozenEvidence.vue";
const props = defineProps<{
  record: PairedRecord<LineageRecord>;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  paperId: string;
  currentSourceSha: string;
  available: boolean;
  initialSelection?: string;
}>();
const focus = useReviewFocus();
function relationChanged() {
  return !props.available || focus.changed("lineage_edges", selectedId.value);
}
function relationEvidenceChanged() {
  return (
    !props.available ||
    props.record.changes.some(
      (c) =>
        (c.domain === "edge_evidence_links" &&
          [c.before?.edge_id, c.after?.edge_id].includes(selectedId.value)) ||
        (c.domain === "evidence" &&
          ["before", "after"].some((side) =>
            props.record[side as "before" | "after"]?.links.some(
              (l) => l.edge_id === selectedId.value && l.evidence_id === c.id,
            ),
          )),
    )
  );
}
const pair = computed(() => lineageGraphPair(props.record)),
  linked = ref(true),
  expanded = ref(false),
  selectedId = ref("");
const viewport = ref<Record<"before" | "after", GraphViewport>>({
  before: { zoom: 0.6, x: 10, y: 10 },
  after: { zoom: 0.6, x: 10, y: 10 },
});
const sides = ["before", "after"] as const;
const unionBounds = computed(() => {
  const nodes = [...pair.value.before.nodes, ...pair.value.after.nodes];
  return {
    width: Math.max(160, ...nodes.map((x) => x.position.x + 80)),
    height: Math.max(120, ...nodes.map((x) => x.position.y + 60)),
  };
});
const edges = computed(() => [
  ...new Map(
    [...pair.value.before.edges, ...pair.value.after.edges].map((x) => [
      x.id,
      x,
    ]),
  ).values(),
]);
const nodes = computed(() => [
  ...new Map(
    [...pair.value.before.nodes, ...pair.value.after.nodes].map((x) => [
      x.id,
      x,
    ]),
  ).values(),
]);
const changeTargets = computed(() => [
  ...new Set(
    [
      ...pair.value.before.edges,
      ...pair.value.after.edges,
      ...pair.value.before.nodes,
      ...pair.value.after.nodes,
    ]
      .filter((x) => x.change !== "unchanged" && x.change !== "unknown")
      .map((x) => x.id),
  ),
]);
const selectedIsEdge = computed(() =>
  edges.value.some((x) => x.id === selectedId.value),
);
function updateViewport(side: "before" | "after", value: GraphViewport) {
  viewport.value = {
    ...viewport.value,
    [side]: value,
    ...(linked.value ? { before: value, after: value } : {}),
  };
}
function navigate(delta: number) {
  const targets = changeTargets.value;
  if (!targets.length) return;
  const index = targets.indexOf(selectedId.value);
  selectedId.value = targets[(index + delta + targets.length) % targets.length];
}
function edge(side: "before" | "after"): Row | undefined {
  return props.record[side]?.edges.find((x) => x.id === selectedId.value);
}
function evidence(side: "before" | "after") {
  const own = props.record[side];
  return (own?.links ?? [])
    .filter((x) => x.edge_id === selectedId.value)
    .map((link) => ({
      link,
      evidence: own?.evidence.find((x) => x.id === link.evidence_id),
    }))
    .sort(
      (a, b) =>
        Number(focus.related("edge_evidence_links", b.link.id)) -
        Number(focus.related("edge_evidence_links", a.link.id)),
    );
}
function compoundName(id: string) {
  return (
    nodes.value.find((x) => x.id === id)?.label ??
    compoundLabel(props.before, id)
  );
}
function label(id: string) {
  const e = edges.value.find((x) => x.id === id);
  return e
    ? `${compoundName(e.source)} → ${compoundName(e.target)}`
    : (nodes.value.find((x) => x.id === id)?.label ?? id);
}
watch(
  () => [props.record.id, props.initialSelection],
  () => {
    selectedId.value =
      props.initialSelection &&
      [...nodes.value, ...edges.value].some(
        (x) => x.id === props.initialSelection,
      )
        ? props.initialSelection
        : (changeTargets.value[0] ??
          edges.value[0]?.id ??
          nodes.value[0]?.id ??
          "");
  },
  { immediate: true },
);
watch(linked, (value) => {
  if (value) viewport.value.after = { ...viewport.value.before };
});
const modal = ref<HTMLElement>();
useModalFocus(expanded, modal);
</script>
<template>
  <section
    ref="modal"
    :role="expanded ? 'dialog' : undefined"
    :aria-modal="expanded ? true : undefined"
    :aria-label="record.label"
    tabindex="-1"
    class="lineage-record-comparison"
    :class="{ 'is-expanded': expanded }"
    data-lineage-comparison
  >
    <header class="lineage-compare-toolbar">
      <div>
        <h3>{{ record.label }}</h3>
        <p>{{ t("共有节点位置保持一致，左右展示完整 Lineage。") }}</p>
      </div>
      <div class="lineage-tools">
        <label
          ><input type="checkbox" v-model="linked" data-graph-sync />{{
            t("联动视图")
          }}</label
        ><button
          class="button-secondary"
          type="button"
          data-graph-expand
          @click="expanded = !expanded"
        >
          {{ t(expanded ? "退出放大对照" : "放大对照") }}
        </button>
      </div>
    </header>
    <div class="graph-legend">
      <span class="added">＋ {{ t("新增") }}</span
      ><span class="removed">− {{ t("删除") }}</span
      ><span class="modified">△ {{ t("已修改") }} / {{ t("证据更新") }}</span
      ><span>{{ t("未变化的节点和关系保留作为上下文") }}</span>
    </div>
    <div class="paired-lineage-graphs">
      <article v-for="side in sides" :key="side">
        <h4 class="record-side-heading">
          {{ t(side === "before" ? "修改前" : "本次提交") }}
        </h4>
        <div class="lineage-description">
          <strong>{{
            record[side]?.lineage.lineage_label ??
            t(
              !available && side === "before"
                ? "比较起点不可用"
                : side === "before"
                  ? "修改前无此条目"
                  : "本次提交已删除",
            )
          }}</strong
          ><span v-if="record[side]">
            ·
            {{
              reviewState(record[side]!.lineage.lineage_type ?? "unspecified")
            }}</span
          >
          <ReviewFields
            v-if="record[side]"
            :row="record[side]!.lineage"
            domain="lineages"
            :fields="['description', 'review_hint']"
          />
        </div>
        <FrozenLineageGraph
          :graph="pair[side]"
          :side="side"
          :viewport="viewport[side]"
          :union-bounds="unionBounds"
          :selected-id="selectedId"
          @select="selectedId = $event"
          @viewport="updateViewport(side, $event)"
          @fit="updateViewport(side, $event)"
        />
      </article>
    </div>
    <nav class="lineage-change-navigation" :aria-label="t('Lineage 变化导航')">
      <button
        class="button-secondary"
        type="button"
        data-change-previous
        :disabled="!changeTargets.length"
        @click="navigate(-1)"
      >
        {{ t("上一处变化") }}</button
      ><strong>{{
        t("{count} 处节点或关系变化", { count: changeTargets.length })
      }}</strong
      ><button
        class="button-secondary"
        type="button"
        data-change-next
        :disabled="!changeTargets.length"
        @click="navigate(1)"
      >
        {{ t("下一处变化") }}
      </button>
    </nav>
    <details class="lineage-entry-list">
      <summary>{{ t("关系与成员目录") }}</summary>
      <div class="lineage-select-list">
        <button
          v-for="e in edges"
          :key="e.id"
          type="button"
          class="button-quiet"
          :class="{ 'is-selected': selectedId === e.id }"
          :aria-pressed="selectedId === e.id"
          data-lineage-relation
          :data-edge-id="e.id"
          @click="selectedId = e.id"
        >
          {{ label(e.id) }}
          <span v-if="e.change !== 'unchanged'"
            >· {{ t(changeLabels[e.change]) }}</span
          ></button
        ><button
          v-for="n in nodes"
          :key="n.id"
          type="button"
          class="button-quiet"
          :class="{ 'is-selected': selectedId === n.id }"
          :aria-pressed="selectedId === n.id"
          data-lineage-member
          :data-compound-id="n.id"
          @click="selectedId = n.id"
        >
          {{ n.label }}
          <span v-if="n.change !== 'unchanged'"
            >· {{ t(changeLabels[n.change]) }}</span
          >
        </button>
      </div>
    </details>
    <h4 v-if="selectedId" class="selected-relation-title">
      {{ t("当前选中") }} · {{ label(selectedId) }}
    </h4>
    <div v-if="selectedIsEdge" class="paired-relation-details">
      <article
        v-for="side in sides"
        :key="side"
        :data-record-side="side"
        class="relation-side"
      >
        <header class="record-side-heading">
          {{ t(side === "before" ? "修改前关系详情" : "本次提交关系详情") }}
        </header>
        <template v-if="edge(side)">
          <p
            class="relation-endpoints"
            data-edge-endpoints
            :style="{ order: -5 }"
          >
            {{
              compoundLabel(
                side === "before" ? before : after,
                String(edge(side)!.parent_compound_id),
              )
            }}
            →
            {{
              compoundLabel(
                side === "before" ? before : after,
                String(edge(side)!.child_compound_id),
              )
            }}
          </p>
          <ReviewDisclosure
            :style="{ order: relationChanged() ? 0 : 10 }"
            :id="`relation:${selectedId}`"
            :label="t('关系说明')"
            :expanded="
              !available ||
              record.changes.some(
                (c) => c.domain === 'lineage_edges' && c.id === selectedId,
              )
            "
          >
            <template #summary
              ><span
                v-if="
                  edge(side)!.review_hint ||
                  edge(side)!.review_status === 'unresolved'
                "
                class="status-chip"
                >{{ t("待核对") }}</span
              ></template
            >
            <ReviewFields
              :row="edge(side)!"
              domain="lineage_edges"
              :fields="[
                'relation_type',
                'modification_summary',
                'review_status',
                'review_hint',
              ]"
            />
          </ReviewDisclosure>
          <ReviewDisclosure
            class="relation-evidence"
            :id="`relation-evidence:${selectedId}`"
            :label="t('关系证据')"
            :expanded="relationEvidenceChanged()"
            :style="{ order: relationEvidenceChanged() ? 1 : 11 }"
          >
            <div v-for="item in evidence(side)" :key="String(item.link.id)">
              <ReviewFields
                :row="item.link"
                domain="edge_evidence_links"
                :fields="['role']"
              />
              <FrozenEvidence
                v-if="item.evidence"
                :evidence="item.evidence"
                :snapshot="side === 'before' ? before : after"
                :paper-id="paperId"
                :current-source-sha="currentSourceSha"
                :change-label="
                  record.changes.some(
                    (c) =>
                      (c.domain === 'evidence' && c.id === item.evidence!.id) ||
                      (c.domain === 'edge_evidence_links' &&
                        c.id === item.link.id),
                  )
                    ? '证据更新'
                    : !available
                      ? '比较起点不可用'
                      : '证据未变'
                "
              />
              <p v-else class="record-issue">{{ t("关联证据不可用") }}</p>
            </div>
            <p v-if="!evidence(side).length">{{ t("无关联证据") }}</p>
          </ReviewDisclosure></template
        >
        <p v-else class="record-absent">
          {{
            t(
              !available && side === "before"
                ? "比较起点不可用，无法还原修改前条目。"
                : side === "before"
                  ? "修改前无此条目"
                  : "本次提交已删除",
            )
          }}
        </p>
      </article>
    </div>
    <div
      v-else-if="selectedId"
      class="paired-node-membership"
      data-node-membership
    >
      <article
        v-for="side in sides"
        :key="side"
        :data-record-side="side"
        class="node-membership-side"
      >
        <h4 class="record-side-heading">
          {{ t(side === "before" ? "修改前" : "本次提交") }}
        </h4>
        <p>
          {{
            pair[side].nodes.find((n) => n.id === selectedId)?.label ??
            label(selectedId)
          }}
        </p>
        <p>
          {{
            t(
              !available
                ? "比较起点不可用"
                : pair[side].nodes.some((n) => n.id === selectedId)
                  ? nodes.find((n) => n.id === selectedId)?.change === "added"
                    ? "新增节点"
                    : nodes.find((n) => n.id === selectedId)?.change ===
                        "removed"
                      ? "删除节点"
                      : "节点未增删"
                  : side === "before"
                    ? "修改前不属于此 Lineage"
                    : "本次提交已移出此 Lineage",
            )
          }}
        </p>
      </article>
    </div>
  </section>
</template>
<style scoped>
.lineage-record-comparison {
  min-width: 0;
}
.lineage-compare-toolbar,
.lineage-tools {
  display: flex;
  gap: 0.7rem;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
}
.lineage-compare-toolbar h3 {
  margin: 0;
}
.lineage-compare-toolbar p {
  font-size: 0.85rem;
  color: var(--ink-muted);
}
.lineage-tools label {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.85rem;
}
.graph-legend {
  display: flex;
  gap: 0.8rem;
  flex-wrap: wrap;
  padding: 0.8rem 0;
  font-size: 0.8rem;
  color: var(--ink-muted);
}
.graph-legend .added {
  color: var(--teal-deep);
}
.graph-legend .removed {
  color: var(--danger);
}
.graph-legend .modified {
  color: var(--amber-deep);
}
.paired-lineage-graphs,
.paired-relation-details,
.paired-node-membership {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.8rem;
}
.paired-lineage-graphs > article {
  min-width: 0;
}
.record-side-heading {
  order: -10;
  margin: 0;
  padding: 0.75rem;
  background: var(--slate-pale);
  font-size: 0.9rem;
}
.paired-lineage-graphs > article:last-child > .record-side-heading,
.relation-side:last-child > .record-side-heading {
  background: var(--teal-pale);
}
.lineage-description {
  min-height: 85px;
  padding: 0.8rem;
  font-size: 0.9rem;
}
.lineage-description p {
  margin: 0.4rem 0;
}
.lineage-change-navigation {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.7rem;
  padding: 1rem 0;
  font-size: 0.85rem;
}
.lineage-entry-list {
  border-block: 1px solid var(--line);
  padding: 0.7rem 0;
}
.lineage-entry-list summary {
  cursor: pointer;
  font-weight: 600;
  font-size: 0.9rem;
}
.lineage-select-list {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
  margin-top: 0.6rem;
}
.lineage-select-list button {
  border: 1px solid var(--line);
  border-radius: 5px;
  font-size: 0.8rem;
}
.lineage-select-list .is-selected {
  background: var(--teal-pale);
  border-color: var(--teal-deep);
}
.relation-side {
  display: grid;
  grid-row: span 4;
  grid-template-rows: subgrid;
  border: 1px solid var(--line);
  border-radius: 6px;
  overflow: hidden;
  min-width: 0;
}
.relation-side > .review-disclosure {
  padding: 0.35rem 0.8rem;
}
.relation-endpoints {
  padding: 0.5rem 0.8rem;
  margin: 0;
  font-size: 0.9rem;
  overflow-wrap: anywhere;
}
.node-membership-side {
  border: 1px solid var(--line);
  border-radius: 6px;
  min-width: 0;
}
.node-membership-side p {
  margin: 0.75rem;
  overflow-wrap: anywhere;
}
.relation-description,
.relation-evidence {
  padding: 0.8rem;
  border-top: 1px solid var(--line);
}
.relation-description p {
  margin: 0.45rem 0;
  font-size: 0.9rem;
  overflow-wrap: anywhere;
}
.record-issue {
  padding: 0.5rem;
  background: var(--amber-pale);
}
.record-resolved {
  color: var(--teal-deep);
}
.record-absent {
  padding: 1.5rem;
  color: var(--ink-muted);
}
.is-expanded {
  position: fixed;
  inset: 0;
  z-index: 1200;
  background: var(--paper, white);
  overflow: auto;
  padding: 1.5rem;
}
.is-expanded :deep(.frozen-graph-canvas) {
  height: 55vh;
}
.selected-relation-title {
  padding: 0.5rem 0;
}
@media (max-width: 700px) {
  .paired-lineage-graphs,
  .paired-relation-details,
  .paired-node-membership {
    grid-template-columns: repeat(2, minmax(285px, 1fr));
    overflow-x: auto;
  }
  .relation-side > .review-disclosure {
    padding: 0.35rem 0.8rem;
  }
  .is-expanded {
    padding: 0.6rem;
  }
  .lineage-change-navigation {
    flex-wrap: wrap;
  }
}
</style>

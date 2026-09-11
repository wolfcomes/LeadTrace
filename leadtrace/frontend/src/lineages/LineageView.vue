<script setup lang="ts">
import { computed } from "vue";

import type { Compound, Lineage, LineageEdge, Structure } from "../api/schema";
import { zhCN } from "../i18n/zh-CN";
import MoleculePairCard from "../structures/MoleculePairCard.vue";


const props = defineProps<{
  lineages: Lineage[];
  edges: LineageEdge[];
  compounds: Compound[];
  structures: Structure[];
}>();

const compoundsById = computed(() => new Map(
  props.compounds.map((compound) => [compound.id, compound]),
));

function edgesFor(lineageId: string): LineageEdge[] {
  return props.edges.filter((edge) => edge.lineage_id === lineageId);
}

function edgeState(edge: LineageEdge): "resolved" | "unresolved" | "invalid" {
  if (
    edge.relation_status === "invalid"
    || edge.parent_compound_id === edge.derived_compound_id
    || !compoundsById.value.has(edge.derived_compound_id)
  ) return "invalid";
  if (
    edge.relation_status === "unresolved"
    || !edge.parent_compound_id
    || !compoundsById.value.has(edge.parent_compound_id)
  ) return "unresolved";
  return "resolved";
}

function edgeLabel(edge: LineageEdge): string {
  const state = edgeState(edge);
  if (state === "invalid") return zhCN.published.lineage.invalid;
  if (state === "unresolved") return zhCN.published.lineage.unresolved;
  return zhCN.published.lineage.confirmed;
}

function compoundLabel(compoundId: string | null): string {
  return compoundId
    ? compoundsById.value.get(compoundId)?.label ?? "—"
    : zhCN.published.lineage.unknownParent;
}

function canRenderPair(edge: LineageEdge): boolean {
  if (!edge.pair_ready || edgeState(edge) !== "resolved" || !edge.parent_compound_id) {
    return false;
  }
  const hasConfirmedStructure = (compoundId: string): boolean => props.structures.some(
    (structure) => structure.compound_id === compoundId
      && structure.state === "structure_confirmed"
      && Boolean(structure.canonical_smiles),
  );
  return hasConfirmedStructure(edge.parent_compound_id)
    && hasConfirmedStructure(edge.derived_compound_id);
}
</script>

<template>
  <div class="lineage-list">
    <article v-for="lineage in lineages" :key="lineage.id" class="lineage-card">
      <header>
        <div>
          <p>{{ zhCN.published.lineage.branch }}</p>
          <h3>{{ lineage.lineage_key }}</h3>
        </div>
        <code>{{ lineage.id }}</code>
      </header>

      <div v-for="edge in edgesFor(lineage.id)" :key="edge.id" class="edge-block">
        <div
          class="edge-summary"
          :class="`is-${edgeState(edge)}`"
          :data-edge-status="edgeState(edge)"
        >
          <div class="edge-state">
            <span aria-hidden="true"></span>
            <strong>{{ edgeLabel(edge) }}</strong>
          </div>
          <div class="edge-route">
            <span>{{ compoundLabel(edge.parent_compound_id) }}</span>
            <b aria-hidden="true">→</b>
            <span>{{ compoundLabel(edge.derived_compound_id) }}</span>
          </div>
          <dl>
            <div>
              <dt>{{ zhCN.published.lineage.relationType }}</dt>
              <dd>{{ edge.relation_type || "—" }}</dd>
            </div>
            <div>
              <dt>Pair</dt>
              <dd>{{ canRenderPair(edge) ? zhCN.published.lineage.pairReady : zhCN.published.lineage.pairBlocked }}</dd>
            </div>
          </dl>
        </div>

        <MoleculePairCard
          v-if="canRenderPair(edge) && edge.parent_compound_id"
          :parent="compoundsById.get(edge.parent_compound_id)!"
          :derived="compoundsById.get(edge.derived_compound_id)!"
          :structures="structures"
        />
      </div>
    </article>
  </div>
</template>

<style scoped>
.lineage-list { display: grid; gap: 16px; }
.lineage-card { overflow: hidden; border: 1px solid var(--line); border-radius: var(--radius-md); background: white; box-shadow: var(--shadow-sm); }
.lineage-card > header { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 18px 20px; border-bottom: 1px solid var(--line); background: #fafbf9; }
.lineage-card header p, .lineage-card header h3 { margin: 0; }
.lineage-card header p { color: var(--gold-700); font-size: .65rem; font-weight: 780; letter-spacing: .09em; }
.lineage-card header h3 { margin-top: 5px; color: var(--ink-950); font: 600 1.1rem/1.2 Georgia, "Noto Serif SC Variable", serif; }
.lineage-card header code { color: var(--ink-500); font-size: .61rem; overflow-wrap: anywhere; }
.edge-block { display: grid; grid-template-columns: minmax(0, .8fr) minmax(320px, 1.2fr); gap: 16px; padding: 18px 20px; border-bottom: 1px solid #edf0ee; }
.edge-block:last-child { border-bottom: 0; }
.edge-summary { padding: 16px; border: 1px solid var(--line); border-left: 4px solid var(--forest-750); border-radius: 10px; background: #fbfcfb; }
.edge-summary.is-unresolved { border-style: dashed; border-left: 4px solid var(--gold-700); background: #fffdf7; }
.edge-summary.is-invalid { border-left-color: var(--danger); background: var(--danger-soft); }
.edge-state { display: flex; align-items: center; gap: 8px; color: var(--forest-750); font-size: .72rem; }
.edge-state span { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.is-unresolved .edge-state { color: var(--gold-700); }
.is-invalid .edge-state { color: var(--danger); }
.edge-route { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); align-items: center; gap: 8px; margin: 17px 0; color: var(--ink-950); font-weight: 720; }
.edge-route span:last-child { text-align: right; }
.edge-route b { color: var(--gold-700); }
dl { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 0; }
dt { color: var(--ink-500); font-size: .64rem; }
dd { margin: 4px 0 0; color: var(--ink-650); font-size: .7rem; overflow-wrap: anywhere; }
@media (max-width: 980px) { .edge-block { grid-template-columns: 1fr; } }
@media (max-width: 560px) { .lineage-card > header { align-items: flex-start; flex-direction: column; } .edge-route { grid-template-columns: 1fr; } .edge-route b { transform: rotate(90deg); text-align: center; } .edge-route span:last-child { text-align: left; } }
</style>

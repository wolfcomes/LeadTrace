<script setup lang="ts">
import { computed } from "vue";

import type { Compound, Structure } from "../api/schema";
import { zhCN } from "../i18n/zh-CN";


const props = defineProps<{
  parent: Compound;
  derived: Compound;
  structures: Structure[];
}>();

function confirmedSmiles(compoundId: string): string | null {
  return props.structures.find(
    (item) => item.compound_id === compoundId
      && item.state === "structure_confirmed"
      && item.canonical_smiles,
  )?.canonical_smiles ?? null;
}

const parentSmiles = computed(() => confirmedSmiles(props.parent.id));
const derivedSmiles = computed(() => confirmedSmiles(props.derived.id));
</script>

<template>
  <article class="molecule-pair panel" data-molecule-pair>
    <div class="pair-heading">
      <span>{{ zhCN.published.lineage.pairReady }}</span>
      <span class="pair-direction" aria-hidden="true">→</span>
    </div>
    <div class="pair-grid">
      <section>
        <p>{{ zhCN.published.lineage.parent }}</p>
        <strong>{{ parent.label }}</strong>
        <code v-if="parentSmiles">{{ parentSmiles }}</code>
        <small v-else>{{ zhCN.published.structure.unavailable }}</small>
      </section>
      <span class="pair-arrow" aria-hidden="true">→</span>
      <section>
        <p>{{ zhCN.published.lineage.derived }}</p>
        <strong>{{ derived.label }}</strong>
        <code v-if="derivedSmiles">{{ derivedSmiles }}</code>
        <small v-else>{{ zhCN.published.structure.unavailable }}</small>
      </section>
    </div>
  </article>
</template>

<style scoped>
.molecule-pair { padding: 18px; box-shadow: none; }
.pair-heading { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; color: var(--teal-deep); font: 600 .65rem/1.2 var(--font-mono); }
.pair-direction { display: grid; width: 24px; height: 24px; place-items: center; color: var(--teal-deep); background: var(--teal-pale); }
.pair-grid { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); align-items: center; gap: 12px; }
.pair-grid section { min-width: 0; padding: 13px; border: 1px solid var(--line); border-radius: var(--radius-sm); background: var(--surface); }
.pair-grid p { margin: 0 0 6px; color: var(--ink-muted); font-size: .66rem; }
.pair-grid strong, .pair-grid code, .pair-grid small { display: block; }
.pair-grid strong { color: var(--ink); font-size: 1.02rem; }
.pair-grid code { margin-top: 9px; overflow-wrap: anywhere; color: var(--ink-muted); font: 500 .68rem/1.45 var(--font-mono); }
.pair-grid small { margin-top: 9px; color: var(--ink-muted); font-size: .64rem; line-height: 1.4; }
.pair-arrow { color: var(--coral-deep); font-size: 1.1rem; }
@media (max-width: 560px) { .pair-grid { grid-template-columns: 1fr; } .pair-arrow { transform: rotate(90deg); text-align: center; } }
</style>

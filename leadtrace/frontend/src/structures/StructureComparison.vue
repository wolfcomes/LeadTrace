<script setup lang="ts">
import { ref } from "vue";
type StructureSide = {
  label: string;
  imageUrl: string | null;
  smiles: string | null;
  structureState?: string;
};

const props = defineProps<{ published: StructureSide; draft: StructureSide }>();
const failed = ref<Record<string, boolean>>({});

const stateLabels: Record<string, string> = {
  proposal: "候选结构",
  parseable_candidate: "RDKit 可解析",
  source_bound_candidate: "已绑定来源",
  structure_confirmed: "结构已确认",
  constitution_confirmed: "仅构造确认",
  non_unique_stereochemistry: "非唯一立体化学",
  multicomponent_unresolved: "多组分未解析",
  source_structure_mismatch: "来源与结构不一致",
  rejected: "已拒绝",
};
</script>

<template>
  <section class="comparison" aria-label="已发布与草稿结构对比">
    <article v-for="side in [props.published, props.draft]" :key="side.label" class="panel" data-structure-side>
      <header>
        <h3>{{ side.label }}</h3>
        <span v-if="side.structureState" class="status-chip" :data-state="side.structureState">{{ stateLabels[side.structureState] ?? side.structureState }}</span>
      </header>
      <img v-if="side.imageUrl && !failed[side.label]" :src="side.imageUrl" :alt="`${side.label}结构图`" @error="failed = { ...failed, [side.label]: true }">
      <div v-else class="unavailable">{{ side.imageUrl ? "结构图加载失败" : "无唯一结构图" }}</div>
      <code v-if="side.smiles">{{ side.smiles }}</code>
      <span v-else class="empty-smiles">未指定唯一 SMILES</span>
    </article>
  </section>
</template>

<style scoped>
.comparison { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
article { display: grid; grid-template-rows: auto minmax(190px, 1fr) auto; gap: 10px; min-width: 0; padding: 14px; }
header { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
h3 { margin: 0; color: var(--ink); font-size: .88rem; }
img { width: 100%; height: 100%; min-height: 190px; object-fit: contain; background: var(--paper); }
.unavailable { display: grid; min-height: 190px; place-items: center; color: var(--ink-muted); background: var(--paper); font-size: .76rem; }
code { overflow-wrap: anywhere; color: var(--ink-soft); font: .68rem/1.5 var(--font-mono); }
.empty-smiles { color: var(--ink-muted); font-size: .7rem; }
@media (max-width: 700px) { .comparison { grid-template-columns: 1fr; } }
</style>

<script setup lang="ts">
type StructureSide = {
  label: string;
  imageUrl: string | null;
  smiles: string | null;
  structureState?: string;
};

const props = defineProps<{ published: StructureSide; draft: StructureSide }>();

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
    <article v-for="side in [props.published, props.draft]" :key="side.label" data-structure-side>
      <header>
        <h3>{{ side.label }}</h3>
        <span v-if="side.structureState">{{ stateLabels[side.structureState] ?? side.structureState }}</span>
      </header>
      <img v-if="side.imageUrl" :src="side.imageUrl" :alt="`${side.label}结构图`">
      <div v-else class="unavailable">无唯一结构图</div>
      <code v-if="side.smiles">{{ side.smiles }}</code>
      <span v-else class="empty-smiles">未指定唯一 SMILES</span>
    </article>
  </section>
</template>

<style scoped>
.comparison { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
article { display: grid; grid-template-rows: auto minmax(190px, 1fr) auto; gap: 10px; min-width: 0; border: 1px solid #d8dee4; padding: 14px; background: #fff; }
header { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
h3 { margin: 0; color: #1f2d38; font-size: .9rem; }
header span { color: #6a4b16; font-size: .72rem; }
img { width: 100%; height: 100%; min-height: 190px; object-fit: contain; background: #f6f8f9; }
.unavailable { display: grid; min-height: 190px; place-items: center; color: #77828b; background: #f3f5f6; font-size: .78rem; }
code { overflow-wrap: anywhere; color: #394650; font-size: .7rem; }
.empty-smiles { color: #7a858e; font-size: .72rem; }
@media (max-width: 700px) { .comparison { grid-template-columns: 1fr; } }
</style>

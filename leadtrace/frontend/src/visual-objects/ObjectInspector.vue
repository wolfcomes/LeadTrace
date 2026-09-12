<script setup lang="ts">
const props = defineProps<{
  object: { id: string; objectKey: string; objectType: string; label?: string | null };
  editable?: boolean;
}>();

const emit = defineEmits<{
  "update-type": [value: string];
  "update-label": [value: string];
}>();

const objectTypes = [
  ["complete_molecule", "完整分子"],
  ["shared_scaffold", "共享骨架"],
  ["r_group", "R 基"],
  ["linker", "连接子"],
  ["variable_site", "可变位点"],
  ["replacement_fragment", "替换片段"],
  ["multi_structure_region", "多结构区域"],
  ["reaction_or_scheme_context", "反应或方案上下文"],
  ["mixed_chemical_region", "混合化学区域"],
  ["non_structure", "非结构内容"],
  ["uncertain", "待确认"],
] as const;
</script>

<template>
  <section class="object-inspector" aria-label="分子对象属性">
    <header>
      <span class="eyebrow">VISUAL OBJECT</span>
      <h2>{{ props.object.objectKey }}</h2>
      <code>{{ props.object.id }}</code>
    </header>
    <label>
      对象类型
      <select
        :value="props.object.objectType"
        :disabled="!props.editable"
        @change="emit('update-type', ($event.target as HTMLSelectElement).value)"
      >
        <option v-for="[value, label] in objectTypes" :key="value" :value="value">{{ label }}</option>
      </select>
    </label>
    <label>
      显示标签
      <input
        :value="props.object.label ?? ''"
        :disabled="!props.editable"
        @input="emit('update-label', ($event.target as HTMLInputElement).value)"
      >
    </label>
  </section>
</template>

<style scoped>
.object-inspector { display: grid; gap: 14px; padding: 16px; border: 1px solid var(--line, #d9e0e6); background: #fff; }
header { display: grid; gap: 4px; }
.eyebrow { color: #6b7785; font-size: .68rem; font-weight: 750; letter-spacing: .1em; }
h2 { margin: 0; color: #1e2b36; font-size: 1rem; }
code { overflow-wrap: anywhere; color: #74808b; font-size: .7rem; }
label { display: grid; gap: 6px; color: #4a5661; font-size: .78rem; font-weight: 650; }
select, input { min-height: 36px; border: 1px solid #cdd6de; border-radius: 5px; padding: 7px 9px; color: #24313d; background: #fff; font: inherit; }
</style>

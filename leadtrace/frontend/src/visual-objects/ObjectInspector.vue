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
  <section class="object-inspector panel" aria-label="分子对象属性">
    <header>
      <span class="eyebrow">VISUAL OBJECT</span>
      <h2>{{ props.object.objectKey }}</h2>
      <code>{{ props.object.id }}</code>
    </header>
    <label class="form-field">
      对象类型
      <select
        class="form-control"
        data-object-type
        :value="props.object.objectType"
        :disabled="!props.editable"
        @change="emit('update-type', ($event.target as HTMLSelectElement).value)"
      >
        <option v-for="[value, label] in objectTypes" :key="value" :value="value">{{ label }}</option>
      </select>
    </label>
    <label class="form-field">
      显示标签
      <input
        class="form-control"
        data-object-label
        :value="props.object.label ?? ''"
        :disabled="!props.editable"
        @input="emit('update-label', ($event.target as HTMLInputElement).value)"
      >
    </label>
  </section>
</template>

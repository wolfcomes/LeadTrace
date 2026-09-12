<script setup lang="ts">
defineProps<{
  bindings: Array<{
    id: string;
    compoundId: string;
    label: string;
    role?: string;
    confidence?: number | null;
    note?: string | null;
  }>;
}>();

const emit = defineEmits<{ select: [id: string] }>();
</script>

<template>
  <section class="binding-panel" aria-label="化合物绑定">
    <header><h2>化合物绑定</h2><span>每个标签保留为独立记录</span></header>
    <ul v-if="bindings.length">
      <li v-for="binding in bindings" :key="binding.id" :data-compound-binding="binding.id">
        <button type="button" @click="emit('select', binding.id)">
          <strong>{{ binding.label }}</strong>
          <span>{{ binding.compoundId }}</span>
        </button>
        <small>{{ binding.role ?? "label" }}<template v-if="binding.confidence != null"> · {{ Math.round(binding.confidence * 100) }}%</template></small>
      </li>
    </ul>
    <p v-else class="empty">暂无化合物绑定</p>
  </section>
</template>

<style scoped>
.binding-panel { display: grid; gap: 12px; padding: 16px; border: 1px solid var(--line, #d9e0e6); background: #fff; }
header { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
h2 { margin: 0; color: #1e2b36; font-size: 1rem; }
header span, small, .empty { color: #6b7785; font-size: .73rem; }
ul { display: grid; gap: 7px; margin: 0; padding: 0; list-style: none; }
li { display: flex; align-items: center; justify-content: space-between; gap: 10px; border-top: 1px solid #edf0f2; padding-top: 9px; }
button { display: grid; gap: 2px; border: 0; padding: 0; color: #1f4e65; background: transparent; text-align: left; cursor: pointer; }
button span { color: #75818d; font-size: .72rem; }
</style>

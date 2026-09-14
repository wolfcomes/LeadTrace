<script setup lang="ts">
defineProps<{
  bindings: Array<{
    id: string;
    compoundId: string;
    label: string;
    role?: string;
    confidence?: number | null;
    note?: string | null;
    operation?: "add" | "update" | "remove";
  }>;
}>();

const emit = defineEmits<{ select: [id: string] }>();

const operationLabels = { add: "新增", update: "修改", remove: "删除" } as const;
</script>

<template>
  <section class="binding-panel panel" aria-label="化合物绑定">
    <header><h2>化合物绑定</h2><span>每个标签保留为独立记录</span></header>
    <ul v-if="bindings.length">
      <li v-for="binding in bindings" :key="binding.id" :class="{ 'is-remove': binding.operation === 'remove' }" :data-compound-binding="binding.id">
        <button class="binding-select" type="button" @click="emit('select', binding.id)">
          <strong>{{ binding.label }}</strong>
          <span>{{ binding.compoundId }}</span>
        </button>
        <div class="binding-meta">
          <span v-if="binding.operation" :class="['operation-badge', 'status-chip', `operation-${binding.operation}`]" data-binding-operation>{{ operationLabels[binding.operation] }}</span>
          <small>{{ binding.role ?? "label" }}<template v-if="binding.confidence != null"> · {{ Math.round(binding.confidence * 100) }}%</template></small>
        </div>
      </li>
    </ul>
    <p v-else class="empty">暂无化合物绑定</p>
  </section>
</template>

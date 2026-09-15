<script setup lang="ts">
defineProps<{
  assets: Array<{ id: string; filename: string; objectCount: number; primary?: boolean; operation?: "add" | "update" | "remove" }>;
  editable?: boolean;
}>();

const emit = defineEmits<{
  select: [id: string];
  remove: [id: string];
  "set-primary": [id: string];
}>();

const operationLabels = { add: "新增", update: "修改", remove: "删除" } as const;
</script>

<template>
  <section class="binding-panel panel" aria-label="图像绑定">
    <header><h2>图像绑定</h2><span>同一裁剪图可重复使用</span></header>
    <ul v-if="assets.length">
      <li v-for="asset in assets" :key="asset.id" :class="{ 'is-remove': asset.operation === 'remove' }" :data-image-binding="asset.id" :data-primary-crop="asset.primary ? '' : undefined">
        <button class="binding-select" type="button" @click="emit('select', asset.id)">
          <strong>{{ asset.filename }}</strong>
          <span>{{ asset.id }}</span>
        </button>
        <div class="binding-meta">
          <span v-if="asset.operation" :class="['operation-badge', 'status-chip', `operation-${asset.operation}`]" data-binding-operation>{{ operationLabels[asset.operation] }}</span>
          <small>{{ asset.objectCount }} 个对象<template v-if="asset.primary"> · 主图</template></small>
          <button v-if="editable && !asset.primary && asset.operation !== 'remove'" class="button-quiet" type="button" @click="emit('set-primary', asset.id)">设为主图</button>
          <button v-if="editable && asset.operation !== 'remove'" class="button-quiet" type="button" @click="emit('remove', asset.id)">移除</button>
        </div>
      </li>
    </ul>
    <p v-else class="empty">暂无图像绑定</p>
  </section>
</template>

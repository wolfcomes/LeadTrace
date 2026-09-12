<script setup lang="ts">
defineProps<{
  assets: Array<{ id: string; filename: string; objectCount: number; primary?: boolean; operation?: "add" | "update" | "remove" }>;
}>();

const emit = defineEmits<{ select: [id: string] }>();

const operationLabels = { add: "新增", update: "修改", remove: "删除" } as const;
</script>

<template>
  <section class="binding-panel" aria-label="图像绑定">
    <header><h2>图像绑定</h2><span>同一裁剪图可重复使用</span></header>
    <ul v-if="assets.length">
      <li v-for="asset in assets" :key="asset.id" :class="{ 'is-remove': asset.operation === 'remove' }" :data-image-binding="asset.id">
        <button type="button" @click="emit('select', asset.id)">
          <strong>{{ asset.filename }}</strong>
          <span>{{ asset.id }}</span>
        </button>
        <div class="binding-meta">
          <span v-if="asset.operation" :class="['operation-badge', `operation-${asset.operation}`]" data-binding-operation>{{ operationLabels[asset.operation] }}</span>
          <small>{{ asset.objectCount }} 个对象<template v-if="asset.primary"> · 主图</template></small>
        </div>
      </li>
    </ul>
    <p v-else class="empty">暂无图像绑定</p>
  </section>
</template>

<style scoped>
.binding-panel { display: grid; gap: 12px; padding: 16px; border: 1px solid var(--line, #d9e0e6); background: #fff; }
header { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
h2 { margin: 0; color: #1e2b36; font-size: 1rem; }
header span, small, .empty { color: #6b7785; font-size: .73rem; }
ul { display: grid; gap: 7px; margin: 0; padding: 0; list-style: none; }
li { display: flex; align-items: center; justify-content: space-between; gap: 10px; border-top: 1px solid #edf0f2; padding-top: 9px; }
li.is-remove { margin-inline: -8px; padding: 9px 8px 0; border-left: 3px solid var(--danger, #a7433c); background: #fff3f2; }
button { display: grid; gap: 2px; border: 0; padding: 0; color: #1f4e65; background: transparent; text-align: left; cursor: pointer; }
button span { color: #75818d; font-size: .72rem; }
.binding-meta { display: grid; gap: 4px; justify-items: end; }
.operation-badge { padding: 3px 6px; border: 1px solid #bcc5ca; border-radius: 4px; font-size: .62rem; font-weight: 750; }
.operation-add { border-color: #8ebaa0; color: #285f45; background: #eef7f1; }.operation-update { border-color: #c7a85d; color: #715718; background: #fff9e9; }.operation-remove { border-color: #d99a95; color: #963b35; background: #fff1f0; }
</style>

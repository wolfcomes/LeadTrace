<script setup lang="ts">
defineProps<{
  assets: Array<{ id: string; filename: string; objectCount: number; primary?: boolean }>;
}>();

const emit = defineEmits<{ select: [id: string] }>();
</script>

<template>
  <section class="binding-panel" aria-label="图像绑定">
    <header><h2>图像绑定</h2><span>同一裁剪图可重复使用</span></header>
    <ul v-if="assets.length">
      <li v-for="asset in assets" :key="asset.id" :data-image-binding="asset.id">
        <button type="button" @click="emit('select', asset.id)">
          <strong>{{ asset.filename }}</strong>
          <span>{{ asset.id }}</span>
        </button>
        <small>{{ asset.objectCount }} 个对象<template v-if="asset.primary"> · 主图</template></small>
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
button { display: grid; gap: 2px; border: 0; padding: 0; color: #1f4e65; background: transparent; text-align: left; cursor: pointer; }
button span { color: #75818d; font-size: .72rem; }
</style>

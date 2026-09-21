<script setup lang="ts">
import { inject, ref } from "vue";
import { previewInstanceKey } from "./api/environment";

const previewInstance = inject(previewInstanceKey, ref<string | null>(null));
</script>

<template>
  <aside v-if="previewInstance" class="preview-environment" data-preview-environment :title="`Preview ${previewInstance}`" aria-label="预览环境">
    <strong>预览环境</strong>
    <span>AI 预填结果 · 待人工复核</span>
    <code>{{ previewInstance.slice(0, 8) }}</code>
  </aside>
  <RouterView />
</template>

<style scoped>
.preview-environment {
  position: sticky;
  top: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  height: 40px;
  padding: 8px 16px;
  color: var(--amber-deep);
  background: var(--amber-pale);
  border-bottom: 2px solid var(--amber);
  font-size: 13px;
  white-space: nowrap;
}
.preview-environment code { opacity: .75; }
@media (max-width: 600px) {
  .preview-environment code { display: none; }
  .preview-environment span { font-size: 12px; }
}
</style>

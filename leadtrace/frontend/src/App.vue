<script setup lang="ts">
import { inject, ref } from "vue";
import { previewInstanceKey } from "./api/environment";
import { locale, setLocale, t, type Locale } from "./i18n";

const previewInstance = inject(previewInstanceKey, ref<string | null>(null));
</script>

<template>
  <aside v-if="previewInstance" class="preview-environment" data-preview-environment :title="`Preview ${previewInstance}`" :aria-label="t('预览环境')">
    <strong>{{ t("预览环境") }}</strong>
    <span>{{ t("AI 预填结果 · 待人工复核") }}</span>
    <code>{{ previewInstance.slice(0, 8) }}</code>
  </aside>
  <div class="language-toolbar">
    <label class="language-control">
      <span aria-hidden="true">{{ t("中 / EN") }}</span>
      <select data-language-switch :value="locale" :aria-label="t('界面语言')" @change="setLocale(($event.target as HTMLSelectElement).value as Locale)">
        <option value="zh-CN">{{ t("中文") }}</option>
        <option value="en">English</option>
      </select>
    </label>
  </div>
  <RouterView />
</template>

<style scoped>
.language-toolbar { position: sticky; top: 0; z-index: 30; display: flex; height: 38px; align-items: center; justify-content: flex-end; padding: 4px 20px; background: var(--paper); border-bottom: 1px solid var(--line); }
.preview-environment + .language-toolbar { top: 40px; }
.language-control { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.language-control select { border: 1px solid var(--line-strong); border-radius: 6px; padding: 4px 8px; background: transparent; color: inherit; }
.language-control select:focus-visible { outline: 2px solid var(--teal); outline-offset: 2px; }

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

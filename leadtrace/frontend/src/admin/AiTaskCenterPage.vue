<script setup lang="ts">
import { t } from "../i18n";
import AiTaskConsole from "./AiTaskConsole.vue";
</script>
<template>
  <div class="admin-page review-workspace">
    <header class="page-heading">
      <div>
        <h1>{{ t("AI 任务中心") }}</h1>
        <p>{{ t("先从文章目录选择文章，再启动生成或独立检查。") }}</p>
      </div>
      <RouterLink class="button-secondary" to="/admin/papers">{{
        t("文章目录")
      }}</RouterLink>
    </header>
    <section class="panel"><AiTaskConsole /></section>
  </div>
</template>

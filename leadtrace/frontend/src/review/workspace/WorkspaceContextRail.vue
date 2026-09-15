<script setup lang="ts">
import { computed } from "vue";

import type { Workspace } from "./types";

const props = defineProps<{
  workspace: Workspace;
  selectedPage?: number;
  selectedVisualObjectId?: string;
}>();

const emit = defineEmits<{
  "select-page": [page: number];
  "select-object": [id: string];
  previous: [];
  next: [];
}>();

const pageObjects = computed(() => props.workspace.visual_objects.filter((visual) => {
  const region = props.workspace.regions.find((item) => item.id === visual.region_id);
  return !props.selectedPage || region?.page_number === props.selectedPage;
}));

const queueLabels: Record<string, string> = {
  localization_or_split: "待定位或切分",
  needs_ocsr: "待 OCSR",
  proposal_review: "OCSR 待审核",
  source_or_attachment: "来源待确认",
  structure_assembly: "结构待确认",
  complete: "已处理",
};
</script>

<template>
  <aside class="workspace-context-rail" data-context-rail aria-label="Paper 核查上下文">
    <header class="context-identity">
      <p class="eyebrow">PAPER SCOPE</p>
      <h2>{{ workspace.paper.title ?? workspace.paper.paper_key }}</h2>
      <code>{{ workspace.paper.paper_key }}</code>
      <span class="status-chip" :data-state="workspace.changeset.workflow_state">
        {{ workspace.changeset.workflow_state }}
      </span>
    </header>

    <section class="context-progress" aria-labelledby="paper-progress-title">
      <div>
        <strong id="paper-progress-title">Paper 进度</strong>
        <span>{{ workspace.progress.resolved_count }} / {{ workspace.progress.scope_count }}</span>
      </div>
      <progress :value="workspace.progress.resolved_count" :max="Math.max(1, workspace.progress.scope_count)"></progress>
      <small>{{ workspace.progress.blocker_count }} 个 blocker</small>
    </section>

    <nav class="context-pages" aria-label="来源页面">
      <strong>页面</strong>
      <button
        v-for="page in workspace.pages"
        :key="page.page_number"
        type="button"
        :aria-current="page.page_number === selectedPage ? 'page' : undefined"
        @click="emit('select-page', page.page_number)"
      >
        <span>p{{ page.page_number }}</span>
        <small>{{ page.visual_object_count }} 对象 · {{ page.blocker_count }} 阻塞</small>
      </button>
    </nav>

    <section class="context-objects" aria-labelledby="page-objects-title">
      <div class="context-section-heading">
        <strong id="page-objects-title">当前页对象</strong>
        <span>{{ pageObjects.length }}</span>
      </div>
      <button
        v-for="visual in pageObjects"
        :key="visual.id"
        type="button"
        :data-visual-object-id="visual.id"
        :aria-current="visual.id === selectedVisualObjectId ? 'true' : undefined"
        @click="emit('select-object', visual.id)"
      >
        <span>{{ visual.object_key }}</span>
        <small><i :class="{ blocking: visual.blocking }" aria-hidden="true"></i>{{ queueLabels[visual.queue_state] }}</small>
      </button>
      <p v-if="pageObjects.length === 0" class="context-empty">当前页没有 molecule object。</p>
    </section>

    <footer class="context-navigation">
      <button class="button-quiet" type="button" data-previous-unresolved @click="emit('previous')">← 上一个未解决</button>
      <button class="button-quiet" type="button" data-next-unresolved @click="emit('next')">下一个未解决 →</button>
      <RouterLink to="/review/tasks?tab=molecules">返回对象队列</RouterLink>
    </footer>
  </aside>
</template>

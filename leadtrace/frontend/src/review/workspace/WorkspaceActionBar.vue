<script setup lang="ts">
import type { AutosaveState } from "../autosave";
import type { Workspace } from "./types";

const props = defineProps<{
  progress: Workspace["progress"];
  unresolvedCount: number;
  saveState?: AutosaveState;
}>();

const emit = defineEmits<{
  previous: [];
  next: [];
  diff: [];
  submit: [];
}>();

const saveLabels: Record<AutosaveState, string> = {
  idle: "已载入",
  pending: "等待保存",
  saving: "正在保存",
  saved: "已保存",
  offline: "离线本地恢复",
  conflict: "版本冲突",
  error: "保存失败",
};
</script>

<template>
  <footer class="workspace-action-bar" data-workspace-action-bar aria-label="工作台状态与操作">
    <div class="action-status" aria-live="polite">
      <span class="status-chip" :data-save-state="props.saveState ?? 'idle'">{{ saveLabels[props.saveState ?? "idle"] }}</span>
      <span><strong>{{ progress.blocker_count }}</strong> 个 blocker</span>
      <span><strong>{{ unresolvedCount }}</strong> 个待处理对象</span>
      <span>{{ progress.resolved_count }} / {{ progress.scope_count }} 已处理</span>
    </div>
    <div class="action-buttons">
      <button class="button-quiet" type="button" @click="emit('previous')">上一个</button>
      <button class="button-quiet" type="button" @click="emit('next')">下一个</button>
      <button class="button-secondary" type="button" @click="emit('diff')">查看 Diff</button>
      <button class="button-primary" type="button" @click="emit('submit')">提交核查</button>
    </div>
  </footer>
</template>

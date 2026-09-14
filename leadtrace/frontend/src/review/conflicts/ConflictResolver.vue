<script setup lang="ts">
import { computed, ref, watch } from "vue";

import type { RecoveryConflict, RecoveryResolution } from "../recovery";

const props = defineProps<{
  open: boolean;
  expectedVersion?: number;
  currentVersion?: number;
  requestId?: string;
  mergeReady?: boolean;
  fields?: RecoveryConflict[];
}>();

const emit = defineEmits<{
  reload: [];
  retry: [resolutions: Record<string, RecoveryResolution>];
}>();

const resolutions = ref<Record<string, RecoveryResolution>>({});
const allResolved = computed(() => (
  (props.fields ?? []).every((field) => resolutions.value[field.key] !== undefined)
));

watch(
  () => [props.open, props.mergeReady, ...(props.fields ?? []).map((field) => field.key)],
  () => { resolutions.value = {}; },
);

function choose(key: string, value: RecoveryResolution): void {
  resolutions.value = { ...resolutions.value, [key]: value };
}

function formatValue(value: unknown, present: boolean): string {
  if (!present) return "未设置";
  if (value === null) return "空值";
  if (typeof value === "string") return value || "空字符串";
  return JSON.stringify(value, null, 2);
}
</script>

<template>
  <div v-if="open" class="conflict-layer" role="dialog" aria-modal="true" aria-labelledby="conflict-title" data-conflict-resolver>
    <section class="conflict-dialog panel">
      <p class="eyebrow">VERSION CONFLICT</p>
      <h2 id="conflict-title">草稿已被其他会话更新</h2>
      <p>本地内容仍保存在恢复缓冲中。系统会保留双方互不冲突的修改；同一字段被双方修改时，需要逐项选择。</p>
      <dl>
        <div><dt>本地基于版本</dt><dd>{{ expectedVersion ?? "—" }}</dd></div>
        <div><dt>服务端当前版本</dt><dd>{{ currentVersion ?? "—" }}</dd></div>
      </dl>
      <small v-if="requestId">请求编号 · {{ requestId }}</small>
      <div v-if="mergeReady" class="merge-fields">
        <p v-if="!fields?.length" class="merge-ready">没有同字段冲突，可以合并双方修改。</p>
        <article v-for="field in fields" :key="field.key" class="merge-field" data-merge-conflict>
          <header><strong>{{ field.label }}</strong><code>{{ field.path }}</code></header>
          <div class="field-choices">
            <button
              type="button"
              :aria-pressed="resolutions[field.key] === 'local'"
              @click="choose(field.key, 'local')"
            >
              <span>本地内容</span>
              <pre>{{ formatValue(field.localValue, field.localPresent) }}</pre>
            </button>
            <button
              type="button"
              :aria-pressed="resolutions[field.key] === 'server'"
              @click="choose(field.key, 'server')"
            >
              <span>服务端内容</span>
              <pre>{{ formatValue(field.serverValue, field.serverPresent) }}</pre>
            </button>
          </div>
        </article>
      </div>
      <div class="conflict-actions">
        <button class="button-secondary" type="button" @click="emit('reload')">使用服务端版本</button>
        <button
          class="button-primary"
          type="button"
          data-apply-merge
          :disabled="mergeReady && !allResolved"
          @click="emit('retry', resolutions)"
        >{{ mergeReady ? (fields?.length ? "应用选择并保存" : "合并非冲突修改") : "载入最新版本并比较" }}</button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.conflict-layer { position: fixed; z-index: 90; inset: 0; display: grid; place-items: center; padding: 24px; background: rgba(23, 43, 60, .62); }
.conflict-dialog { width: min(100%, 510px); padding: 28px; border-top: 4px solid var(--danger); box-shadow: 0 28px 80px rgba(23, 43, 60, .25); }
.conflict-dialog h2 { margin: 0; color: var(--ink); font: 600 1.55rem/1.25 var(--font-serif); }
.conflict-dialog > p:not(.eyebrow) { margin: 14px 0 0; color: var(--ink-muted); font-size: .81rem; line-height: 1.7; }
dl { display: grid; grid-template-columns: repeat(2, 1fr); margin: 22px 0 0; border-block: 1px solid var(--line); }
dl div { padding: 14px 0; }
dt { color: var(--ink-muted); font-size: .63rem; }
dd { margin: 5px 0 0; color: var(--ink); font-weight: 760; }
.conflict-dialog small { display: block; margin-top: 13px; color: var(--ink-muted); font-size: .64rem; }
.merge-fields { display: grid; gap: 12px; max-height: min(46vh, 440px); margin-top: 18px; overflow-y: auto; }
.merge-ready { margin: 0; padding: 12px; color: var(--teal-deep); background: var(--teal-pale); font-size: .73rem; }
.merge-field { padding: 13px; border: 1px solid var(--line); background: var(--paper); }
.merge-field header { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.merge-field header strong { color: var(--ink-soft); font-size: .72rem; }
.merge-field header code { overflow-wrap: anywhere; color: var(--ink-muted); font-size: .57rem; }
.field-choices { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; margin-top: 10px; }
.field-choices button { min-width: 0; padding: 10px; border: 1px solid var(--line); color: var(--ink-muted); background: var(--surface); text-align: left; cursor: pointer; }
.field-choices button[aria-pressed="true"] { border-color: var(--coral); box-shadow: inset 0 0 0 1px var(--coral); background: var(--coral-pale); }
.field-choices span { display: block; color: var(--coral-deep); font-size: .62rem; font-weight: 760; }
.field-choices pre { max-height: 90px; margin: 7px 0 0; overflow: auto; font: .62rem/1.45 var(--font-mono); white-space: pre-wrap; overflow-wrap: anywhere; }
.conflict-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 24px; }
.conflict-actions button { min-height: 40px; padding: 8px 13px; }
@media (max-width: 540px) { dl, .field-choices { grid-template-columns: 1fr; } .conflict-actions { align-items: stretch; flex-direction: column-reverse; } }
</style>

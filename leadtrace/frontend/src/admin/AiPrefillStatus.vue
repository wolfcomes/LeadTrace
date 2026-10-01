<script setup lang="ts">
import { t, locale } from "../i18n";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";

import { ApiError } from "../api/client";
import { useAuthStore } from "../auth/store";
import { getAiPrefillStatus, startAiPrefill } from "../v2/api";
import type { AiPrefillStatus } from "../v2/types";


const props = withDefaults(defineProps<{
  paperId: string;
  status: AiPrefillStatus;
  compact?: boolean;
  interactive?: boolean;
  poll?: boolean;
}>(), {
  compact: false,
  interactive: false,
  poll: false,
});

const emit = defineEmits<{
  update: [status: AiPrefillStatus];
}>();

const POLL_INTERVAL_MS = 2_000;
const MAX_POLL_ATTEMPTS = 30;
const auth = useAuthStore();
const current = ref<AiPrefillStatus>(props.status);
const busy = ref(false);
const errorMessage = ref<string>();
const errorRequestId = ref<string>();
let pollAttempts = 0;
let pollTimer: ReturnType<typeof setTimeout> | undefined;

const runStatus = computed(() => current.value.run?.status);
const active = computed(() => runStatus.value === "queued" || runStatus.value === "running");
const statusLabel = computed(() => {
  if (!runStatus.value) return current.value.can_start ? "可启动" : "未运行";
  return {
    queued: "已排队",
    running: "提取中",
    succeeded: "预填完成",
    failed: "预填失败",
    superseded: "已失效",
  }[runStatus.value];
});
const actionLabel = computed(() => {
  if (busy.value) return "正在启动";
  if (runStatus.value === "failed") return "重新运行 AI 预填";
  if (active.value) return "AI 预填进行中";
  if (runStatus.value === "succeeded") return "AI 预填已完成";
  return "启动 AI 预填";
});

function stopPolling(): void {
  if (pollTimer !== undefined) clearTimeout(pollTimer);
  pollTimer = undefined;
}

function schedulePoll(): void {
  stopPolling();
  if (!props.poll || !active.value || pollAttempts >= MAX_POLL_ATTEMPTS) return;
  pollTimer = setTimeout(() => void refreshStatus(), POLL_INTERVAL_MS);
}

async function refreshStatus(): Promise<void> {
  pollTimer = undefined;
  pollAttempts += 1;
  try {
    current.value = await getAiPrefillStatus(props.paperId);
    emit("update", current.value);
  } catch {
    errorMessage.value = "暂时无法刷新 AI 预填状态。";
  }
  schedulePoll();
}

async function start(): Promise<void> {
  if (busy.value || !current.value.can_start) return;
  busy.value = true;
  errorMessage.value = undefined;
  stopPolling();
  try {
    current.value = await startAiPrefill(props.paperId, auth.csrfToken);
    emit("update", current.value);
    pollAttempts = 0;
    schedulePoll();
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      current.value = {
        ...current.value,
        can_start: false,
        blocked_reason: "Workspace has already been modified",
      };
      errorMessage.value = "Workspace 已发生变化，AI 预填未启动。";
      errorRequestId.value = error.requestId;
    } else {
      const requestId = error instanceof ApiError ? error.requestId : undefined;
      errorMessage.value = "暂时无法启动 AI 预填。";
      errorRequestId.value = requestId;
    }
  } finally {
    busy.value = false;
  }
}

watch(() => props.status, (value) => {
  current.value = value;
  errorMessage.value = undefined;
  schedulePoll();
});

onMounted(schedulePoll);
onBeforeUnmount(stopPolling);
</script>

<template>
  <div :class="['ai-prefill-status', { compact }]" data-ai-prefill-status>
    <span class="status-chip" :data-status="runStatus ?? (current.can_start ? 'ready' : 'unavailable')">
      {{ t(statusLabel) }}
    </span>
    <small v-if="!compact && current.run">{{ current.run.engine }} · {{ current.run.engine_version }}</small>
    <small v-if="!compact && current.blocked_reason">{{ current.blocked_reason }}</small>
    <button
      v-if="interactive"
      class="button-secondary full"
      data-ai-prefill-start
      type="button"
      :disabled="busy || !current.can_start"
      :title="current.blocked_reason ?? t(actionLabel)"
      @click="start"
    >{{ t(actionLabel) }}</button>
    <p v-if="errorMessage" class="inline-feedback is-error" data-ai-prefill-error role="alert">
      {{ t(errorMessage) }} <small v-if="errorRequestId">{{ t("请求编号：{requestId}", { requestId: errorRequestId }) }}</small>
    </p>
  </div>
</template>

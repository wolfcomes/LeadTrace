<script setup lang="ts">
import { t } from "../../i18n";
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

import { createSetMoleculeMessage, parseChildMessage } from "./ketcherProtocol";

const READY_TIMEOUT_MS = 15_000;
const REQUEST_TIMEOUT_MS = 15_000;

const props = withDefaults(defineProps<{ modelValue?: string | null; disabled?: boolean }>(), {
  modelValue: null,
  disabled: false,
});
const emit = defineEmits<{ "update:modelValue": [molfile: string]; error: [message: string] }>();

const frame = ref<HTMLIFrameElement>();
const ready = ref(false);
const failed = ref(false);
let listening = false;
let readyTimeout: ReturnType<typeof setTimeout> | undefined;
let requestTimeout: ReturnType<typeof setTimeout> | undefined;
let pendingMolecule = props.modelValue ?? "";
let currentMolfile = "";
let lastEmittedMolfile: string | undefined;
let nextRequestId = 0;

type PendingRequest = {
  requestId: number;
  promise: Promise<void>;
  resolve: () => void;
  reject: (reason: Error) => void;
  status: "pending" | "resolved" | "failed";
  error?: Error;
};

let activeRequest: PendingRequest | undefined;

function createPendingRequest(requestId: number): PendingRequest {
  let resolve!: () => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<void>((finish, fail) => {
    resolve = finish;
    reject = fail;
  });
  void promise.catch(() => undefined);
  return { requestId, promise, resolve, reject, status: "pending" };
}

function clearReadyTimeout(): void {
  if (readyTimeout !== undefined) clearTimeout(readyTimeout);
  readyTimeout = undefined;
}

function clearRequestTimeout(): void {
  if (requestTimeout !== undefined) clearTimeout(requestTimeout);
  requestTimeout = undefined;
}

function postMolecule(value: string): void {
  if (!ready.value || !frame.value?.contentWindow || !activeRequest) return;
  const requestId = activeRequest.requestId;
  frame.value.contentWindow.postMessage(
    createSetMoleculeMessage(requestId, value),
    window.location.origin,
  );
  clearRequestTimeout();
  requestTimeout = setTimeout(() => {
    if (
      activeRequest?.requestId !== requestId
      || activeRequest.status !== "pending"
    ) return;
    const message = "Ketcher 编辑器未能处理当前结构，请重试。";
    const error = new Error(message);
    activeRequest.reject(error);
    activeRequest.status = "failed";
    activeRequest.error = error;
    requestTimeout = undefined;
    emit("error", message);
  }, REQUEST_TIMEOUT_MS);
}

function setMolecule(value: string | null | undefined): Promise<void> {
  if (props.disabled) return Promise.reject(new Error("Ketcher 编辑器已停用。"));
  pendingMolecule = value ?? "";
  lastEmittedMolfile = undefined;
  clearRequestTimeout();
  if (activeRequest?.status === "pending") {
    activeRequest.reject(new Error("Ketcher molecule request was superseded."));
  }
  activeRequest = createPendingRequest(++nextRequestId);
  postMolecule(pendingMolecule);
  return activeRequest.promise;
}

function handleMessage(event: MessageEvent): void {
  if (event.origin !== window.location.origin || event.source !== frame.value?.contentWindow) return;
  const message = parseChildMessage(event.data);
  if (!message) return;

  if (message.kind === "ready") {
    clearReadyTimeout();
    failed.value = false;
    ready.value = true;
    if (!activeRequest) {
      void setMolecule(pendingMolecule);
    } else {
      postMolecule(pendingMolecule);
    }
    return;
  }
  if (message.kind === "molfile") {
    if (message.requestId !== activeRequest?.requestId) return;
    clearRequestTimeout();
    currentMolfile = message.molfile;
    pendingMolecule = message.molfile;
    lastEmittedMolfile = message.molfile;
    if (activeRequest.status === "pending") activeRequest.resolve();
    activeRequest.status = "resolved";
    activeRequest.error = undefined;
    emit("update:modelValue", message.molfile);
    return;
  }
  if (message.requestId !== null && message.requestId !== activeRequest?.requestId) return;
  if (message.requestId !== null && activeRequest) {
    clearRequestTimeout();
    const error = new Error(message.message || "Ketcher 编辑器发生错误。");
    if (activeRequest.status === "pending") activeRequest.reject(error);
    activeRequest.status = "failed";
    activeRequest.error = error;
  }
  emit("error", message.message || "Ketcher 编辑器发生错误。");
}

async function start(): Promise<void> {
  if (props.disabled || listening) return;
  listening = true;
  failed.value = false;
  ready.value = false;
  window.addEventListener("message", handleMessage);
  await nextTick();
  if (props.disabled || !listening || !frame.value) return;
  clearReadyTimeout();
  readyTimeout = setTimeout(() => {
    if (!ready.value && listening) {
      failed.value = true;
      const message = "Ketcher 编辑器未能载入，请重试。";
      clearRequestTimeout();
      if (activeRequest?.status === "pending") activeRequest.reject(new Error(message));
      activeRequest = undefined;
      emit("error", message);
    }
  }, READY_TIMEOUT_MS);
}

function stop(): void {
  clearReadyTimeout();
  clearRequestTimeout();
  failed.value = false;
  ready.value = false;
  if (listening) window.removeEventListener("message", handleMessage);
  listening = false;
  lastEmittedMolfile = undefined;
  if (activeRequest?.status === "pending") {
    activeRequest.reject(new Error("Ketcher editor stopped before the molecule request completed."));
  }
  activeRequest = undefined;
}

watch(() => props.modelValue, (value) => {
  if (value === lastEmittedMolfile) return;
  if (props.disabled) {
    pendingMolecule = value ?? "";
    lastEmittedMolfile = undefined;
    return;
  }
  void setMolecule(value);
});
watch(() => props.disabled, (disabled) => {
  if (disabled) stop();
  else {
    void setMolecule(pendingMolecule);
    void start();
  }
});
onMounted(() => { void start(); });
onBeforeUnmount(stop);

if (!props.disabled) void setMolecule(pendingMolecule);

defineExpose({
  getMolfile: async () => {
    if (props.disabled) throw new Error("Ketcher 编辑器已停用。");
    if (activeRequest?.status === "pending") await activeRequest.promise;
    if (activeRequest?.status === "failed") throw activeRequest.error;
    return currentMolfile;
  },
  setMolecule,
});
</script>

<template>
  <section class="ketcher-island" data-ketcher-editor :aria-label='t("Ketcher 化学结构编辑器")'>
    <p v-if="disabled" class="workspace-empty-copy">{{ t("当前 Workspace 为只读，Ketcher 已停用。") }}</p>
    <template v-else>
      <p v-if="failed" class="ketcher-failed" role="alert">{{ t("Ketcher 编辑器未能载入，请关闭后重试。") }}</p>
      <p v-else-if="!ready" class="ketcher-loading" aria-live="polite">{{ t("正在载入本地 Ketcher 编辑器…") }}</p>
      <iframe ref="frame" class="ketcher-frame" src="/ketcher.html" :title='t("Ketcher 化学结构编辑器")'></iframe>
    </template>
  </section>
</template>

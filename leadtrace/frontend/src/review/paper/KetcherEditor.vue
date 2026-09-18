<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

import { createSetMoleculeMessage, parseChildMessage } from "./ketcherProtocol";

const READY_TIMEOUT_MS = 15_000;

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
let pendingMolecule = props.modelValue ?? "";
let currentMolfile = "";
let lastEmittedMolfile: string | undefined;
let nextRequestId = 0;

type PendingRequest = {
  requestId: number;
  promise: Promise<void>;
  resolve: () => void;
  reject: (reason: Error) => void;
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
  return { requestId, promise, resolve, reject };
}

function clearReadyTimeout(): void {
  if (readyTimeout !== undefined) clearTimeout(readyTimeout);
  readyTimeout = undefined;
}

function postMolecule(value: string): void {
  if (!ready.value || !frame.value?.contentWindow || !activeRequest) return;
  frame.value.contentWindow.postMessage(
    createSetMoleculeMessage(activeRequest.requestId, value),
    window.location.origin,
  );
}

function setMolecule(value: string | null | undefined): Promise<void> {
  if (props.disabled) return Promise.reject(new Error("Ketcher 编辑器已停用。"));
  activeRequest?.reject(new Error("Ketcher molecule request was superseded."));
  pendingMolecule = value ?? "";
  lastEmittedMolfile = undefined;
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
    currentMolfile = message.molfile;
    lastEmittedMolfile = message.molfile;
    activeRequest.resolve();
    emit("update:modelValue", message.molfile);
    return;
  }
  if (message.requestId !== null && message.requestId !== activeRequest?.requestId) return;
  if (message.requestId !== null) activeRequest?.reject(new Error(message.message || "Ketcher 编辑器发生错误。"));
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
      activeRequest?.reject(new Error(message));
      activeRequest = undefined;
      emit("error", message);
    }
  }, READY_TIMEOUT_MS);
}

function stop(): void {
  clearReadyTimeout();
  failed.value = false;
  ready.value = false;
  if (listening) window.removeEventListener("message", handleMessage);
  listening = false;
  lastEmittedMolfile = undefined;
  activeRequest?.reject(new Error("Ketcher editor stopped before the molecule request completed."));
  activeRequest = undefined;
}

watch(() => props.modelValue, (value) => {
  if (value === lastEmittedMolfile) return;
  setMolecule(value);
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
    await activeRequest?.promise;
    return currentMolfile;
  },
  setMolecule,
});
</script>

<template>
  <section class="ketcher-island" data-ketcher-editor aria-label="Ketcher 化学结构编辑器">
    <p v-if="disabled" class="workspace-empty-copy">当前 Workspace 为只读，Ketcher 已停用。</p>
    <template v-else>
      <p v-if="failed" class="ketcher-failed" role="alert">Ketcher 编辑器未能载入，请关闭后重试。</p>
      <p v-else-if="!ready" class="ketcher-loading" aria-live="polite">正在载入本地 Ketcher 编辑器…</p>
      <iframe ref="frame" class="ketcher-frame" src="/ketcher.html" title="Ketcher 化学结构编辑器"></iframe>
    </template>
  </section>
</template>

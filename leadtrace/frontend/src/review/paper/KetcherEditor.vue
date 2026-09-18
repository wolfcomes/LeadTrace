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
let currentMolfile = props.modelValue ?? "";
let lastEmittedMolfile: string | undefined;

function clearReadyTimeout(): void {
  if (readyTimeout !== undefined) clearTimeout(readyTimeout);
  readyTimeout = undefined;
}

function postMolecule(value: string): void {
  if (!ready.value || !frame.value?.contentWindow) return;
  frame.value.contentWindow.postMessage(createSetMoleculeMessage(value), window.location.origin);
}

function setMolecule(value: string | null | undefined): void {
  pendingMolecule = value ?? "";
  currentMolfile = pendingMolecule;
  lastEmittedMolfile = undefined;
  postMolecule(pendingMolecule);
}

function handleMessage(event: MessageEvent): void {
  if (event.origin !== window.location.origin || event.source !== frame.value?.contentWindow) return;
  const message = parseChildMessage(event.data);
  if (!message) return;

  if (message.kind === "ready") {
    clearReadyTimeout();
    failed.value = false;
    ready.value = true;
    postMolecule(pendingMolecule);
    return;
  }
  if (message.kind === "molfile") {
    currentMolfile = message.molfile;
    lastEmittedMolfile = message.molfile;
    emit("update:modelValue", message.molfile);
    return;
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
      emit("error", "Ketcher 编辑器未能载入，请重试。");
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
}

watch(() => props.modelValue, (value) => {
  if (value === lastEmittedMolfile) return;
  setMolecule(value);
});
watch(() => props.disabled, (disabled) => {
  if (disabled) stop();
  else void start();
});
onMounted(() => { void start(); });
onBeforeUnmount(stop);

defineExpose({
  getMolfile: async () => currentMolfile,
  setMolecule: async (value: string | null | undefined) => { setMolecule(value); },
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

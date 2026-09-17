<script setup lang="ts">
import type { Ketcher } from "ketcher-core";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { Root } from "react-dom/client";

const props = withDefaults(defineProps<{ modelValue?: string | null; disabled?: boolean }>(), {
  modelValue: null,
  disabled: false,
});
const emit = defineEmits<{ "update:modelValue": [molfile: string]; error: [message: string] }>();

const host = ref<HTMLDivElement>();
const ready = ref(false);
let reactRoot: Root | undefined;
let ketcher: Ketcher | undefined;
let applyingExternalValue = false;
let disposed = false;
let mountSequence = 0;
let outputSequence = 0;
let lastEmittedMolfile: string | undefined;

async function applyMolecule(value: string | null | undefined): Promise<void> {
  if (!ketcher || !value) return;
  applyingExternalValue = true;
  try {
    await ketcher.setMolecule(value);
  } catch {
    emit("error", "Ketcher 无法载入当前结构文本。");
  } finally {
    applyingExternalValue = false;
  }
}

async function emitMolfile(): Promise<void> {
  if (!ketcher || applyingExternalValue) return;
  const sequence = ++outputSequence;
  try {
    const value = await ketcher.getMolfile();
    if (disposed || sequence !== outputSequence) return;
    lastEmittedMolfile = value;
    emit("update:modelValue", value);
  } catch {
    emit("error", "Ketcher 暂时无法导出 Molfile。");
  }
}

function initialize(api: Ketcher): void {
  if (disposed || props.disabled || !reactRoot) return;
  ketcher = api;
  ketcher.changeEvent.add(emitMolfile);
  void (async () => {
    await applyMolecule(props.modelValue);
    if (props.modelValue && !disposed && !props.disabled && ketcher === api) {
      await emitMolfile();
    }
    if (!disposed && !props.disabled && ketcher === api) ready.value = true;
  })();
}

function teardown(): void {
  mountSequence += 1;
  outputSequence += 1;
  lastEmittedMolfile = undefined;
  ready.value = false;
  if (ketcher) ketcher.changeEvent.remove(emitMolfile);
  ketcher = undefined;
  reactRoot?.unmount();
  reactRoot = undefined;
  applyingExternalValue = false;
}

async function mountEditor(): Promise<void> {
  if (!host.value || props.disabled || disposed || reactRoot) return;
  const sequence = ++mountSequence;
  ready.value = false;
  try {
    const [react, reactDom, ketcherReact, ketcherStandalone] = await Promise.all([
      import("react"),
      import("react-dom/client"),
      import("ketcher-react"),
      import("ketcher-standalone"),
      import("ketcher-react/dist/index.css"),
    ]);
    if (disposed || props.disabled || sequence !== mountSequence || !host.value) return;
    const serviceProvider = new ketcherStandalone.StandaloneStructServiceProvider();
    reactRoot = reactDom.createRoot(host.value);
    reactRoot.render(react.createElement(ketcherReact.Editor, {
      staticResourcesUrl: "",
      structServiceProvider: serviceProvider,
      errorHandler: (message: string) => emit("error", message || "Ketcher 编辑器发生错误。"),
      onInit: initialize,
      disableMacromoleculesEditor: true,
    }));
  } catch {
    if (!disposed && !props.disabled && sequence === mountSequence) {
      emit("error", "Ketcher 编辑器未能载入，请重试。");
    }
  }
}

watch(() => props.modelValue, (value) => {
  if (value === lastEmittedMolfile) return;
  void applyMolecule(value);
});
watch(() => props.disabled, (disabled) => {
  if (disabled) teardown();
  else void mountEditor();
});
onMounted(() => { void mountEditor(); });
onBeforeUnmount(() => {
  disposed = true;
  teardown();
});

defineExpose({
  getMolfile: async () => ketcher?.getMolfile() ?? props.modelValue ?? "",
  setMolecule: applyMolecule,
});
</script>

<template>
  <section class="ketcher-island" data-ketcher-editor aria-label="Ketcher 化学结构编辑器">
    <p v-if="disabled" class="workspace-empty-copy">当前 Workspace 为只读，Ketcher 已停用。</p>
    <p v-else-if="!ready" class="ketcher-loading" aria-live="polite">正在载入本地 Ketcher 编辑器…</p>
    <div v-show="!disabled" ref="host" class="ketcher-react-host"></div>
  </section>
</template>

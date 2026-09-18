<script setup lang="ts">
import { computed, ref } from "vue";

import { normalizePdfRegionBounds, type PdfRegionBounds } from "./geometry";

export interface PdfRegion {
  id: string;
  regionKey?: string;
  pageNumber: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  rotation: number;
  tombstone?: boolean;
}

const props = defineProps<{
  region: PdfRegion;
  selected?: boolean;
  readOnly?: boolean;
}>();

const emit = defineEmits<{
  select: [id: string];
  duplicate: [id: string];
  move: [payload: { id: string; x0: number; y0: number; x1: number; y1: number }];
  resize: [payload: { id: string; x0: number; y0: number; x1: number; y1: number }];
}>();

type ResizeHandle = "nw" | "ne" | "sw" | "se";
type Interaction = {
  kind: "move" | "resize";
  handle?: ResizeHandle;
  startX: number;
  startY: number;
  bounds: PdfRegionBounds;
};

const interaction = ref<Interaction | null>(null);

const style = computed(() => ({
  left: `${props.region.x0 * 100}%`,
  top: `${props.region.y0 * 100}%`,
  width: `${(props.region.x1 - props.region.x0) * 100}%`,
  height: `${(props.region.y1 - props.region.y0) * 100}%`,
  transform: `rotate(${props.region.rotation}deg)`,
}));

function clamp(value: number, minimum = 0, maximum = 1): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function pageRect(target: EventTarget | null): { left: number; top: number; width: number; height: number } {
  const element = target instanceof HTMLElement ? target : null;
  const page = element?.closest<HTMLElement>("[data-pdf-page]");
  const rect = page?.getBoundingClientRect();
  return {
    left: rect?.left ?? 0,
    top: rect?.top ?? 0,
    width: rect?.width || 800,
    height: rect?.height || 400,
  };
}

function beginMove(event: PointerEvent): void {
  if (props.readOnly) return;
  emit("select", props.region.id);
  (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
  interaction.value = {
    kind: "move",
    startX: event.clientX,
    startY: event.clientY,
    bounds: {
      x0: props.region.x0,
      y0: props.region.y0,
      x1: props.region.x1,
      y1: props.region.y1,
    },
  };
}

function beginResize(handle: ResizeHandle, event: PointerEvent): void {
  if (props.readOnly) return;
  (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
  interaction.value = {
    kind: "resize",
    handle,
    startX: event.clientX,
    startY: event.clientY,
    bounds: {
      x0: props.region.x0,
      y0: props.region.y0,
      x1: props.region.x1,
      y1: props.region.y1,
    },
  };
}

function nextBounds(event: PointerEvent) {
  const active = interaction.value;
  if (!active) return null;
  const rect = pageRect(event.currentTarget);
  const dx = (event.clientX - active.startX) / rect.width;
  const dy = (event.clientY - active.startY) / rect.height;
  const bounds = { ...active.bounds };
  if (active.kind === "move") {
    const width = bounds.x1 - bounds.x0;
    const height = bounds.y1 - bounds.y0;
    bounds.x0 = clamp(bounds.x0 + dx, 0, 1 - width);
    bounds.y0 = clamp(bounds.y0 + dy, 0, 1 - height);
    bounds.x1 = bounds.x0 + width;
    bounds.y1 = bounds.y0 + height;
  } else {
    const handle = active.handle ?? "se";
    if (handle.includes("w")) bounds.x0 = clamp(bounds.x0 + dx, 0, bounds.x1 - 0.01);
    if (handle.includes("e")) bounds.x1 = clamp(bounds.x1 + dx, bounds.x0 + 0.01, 1);
    if (handle.includes("n")) bounds.y0 = clamp(bounds.y0 + dy, 0, bounds.y1 - 0.01);
    if (handle.includes("s")) bounds.y1 = clamp(bounds.y1 + dy, bounds.y0 + 0.01, 1);
  }
  const normalized = normalizePdfRegionBounds(bounds);
  return normalized ? { id: props.region.id, ...normalized } : null;
}

function finishInteraction(event: PointerEvent): void {
  const active = interaction.value;
  if (!active) return;
  const bounds = nextBounds(event);
  interaction.value = null;
  if (!bounds) return;
  if (active.kind === "move") emit("move", bounds);
  else emit("resize", bounds);
}
</script>

<template>
  <div
    class="region-overlay"
    :class="{ selected, tombstone: region.tombstone }"
    :style="style"
    :data-region-id="region.id"
    role="button"
    tabindex="0"
    :aria-label="`区域 ${region.regionKey ?? region.id}`"
    @click.stop="emit('select', region.id)"
    @dblclick.stop="emit('duplicate', region.id)"
    @keydown.enter.stop="emit('select', region.id)"
    @keydown.space.prevent.stop="emit('select', region.id)"
    @pointerdown.stop="beginMove"
    @pointermove.stop
    @pointerup.stop="finishInteraction"
    @pointercancel.stop="interaction = null"
  >
    <span class="region-label">{{ region.regionKey ?? region.id }}</span>
    <template v-if="selected && !readOnly">
      <button
        v-for="handle in (['nw', 'ne', 'sw', 'se'] as const)"
        :key="handle"
        class="resize-handle"
        :class="`resize-handle--${handle}`"
        :data-resize-handle="handle"
        type="button"
        :aria-label="`调整区域 ${region.regionKey ?? region.id} ${handle}`"
        @click.stop
        @dblclick.stop
        @pointerdown.stop="beginResize(handle, $event)"
        @pointermove.stop
        @pointerup.stop="finishInteraction"
        @pointercancel.stop="interaction = null"
      ></button>
    </template>
  </div>
</template>

<style scoped>
.region-overlay {
  position: absolute;
  min-width: 12px;
  min-height: 12px;
  border: 2px solid var(--teal);
  background: color-mix(in srgb, var(--teal) 12%, transparent);
  cursor: move;
  padding: 0;
  text-align: left;
}
.region-overlay:focus-visible { outline: 3px solid color-mix(in srgb, var(--coral) 55%, transparent); outline-offset: 2px; }
.region-overlay.selected {
  border-color: var(--coral-deep);
  background: color-mix(in srgb, var(--coral) 14%, transparent);
}
.region-overlay.tombstone {
  opacity: .45;
  border-style: dashed;
}
.region-label {
  position: absolute;
  top: -1.4rem;
  left: -2px;
  padding: 2px 5px;
  color: white;
  background: var(--ink);
  font-size: 11px;
  white-space: nowrap;
}
.resize-handle { position: absolute; width: 12px; height: 12px; padding: 0; border: 2px solid white; border-radius: 50%; background: var(--coral-deep); }
.resize-handle--nw { top: -7px; left: -7px; cursor: nwse-resize; }
.resize-handle--ne { top: -7px; right: -7px; cursor: nesw-resize; }
.resize-handle--sw { bottom: -7px; left: -7px; cursor: nesw-resize; }
.resize-handle--se { right: -7px; bottom: -7px; cursor: nwse-resize; }
</style>

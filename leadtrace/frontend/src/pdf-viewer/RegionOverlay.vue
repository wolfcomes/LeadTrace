<script setup lang="ts">
import { computed } from "vue";

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
}>();

const emit = defineEmits<{
  select: [id: string];
  duplicate: [id: string];
  move: [payload: { id: string; x0: number; y0: number; x1: number; y1: number }];
}>();

const style = computed(() => ({
  left: `${props.region.x0 * 100}%`,
  top: `${props.region.y0 * 100}%`,
  width: `${(props.region.x1 - props.region.x0) * 100}%`,
  height: `${(props.region.y1 - props.region.y0) * 100}%`,
  transform: `rotate(${props.region.rotation}deg)`,
}));
</script>

<template>
  <button
    class="region-overlay"
    :class="{ selected, tombstone: region.tombstone }"
    :style="style"
    :data-region-id="region.id"
    type="button"
    role="button"
    :aria-label="`区域 ${region.regionKey ?? region.id}`"
    @click.stop="emit('select', region.id)"
    @dblclick.stop="emit('duplicate', region.id)"
  >
    <span class="region-label">{{ region.regionKey ?? region.id }}</span>
  </button>
</template>

<style scoped>
.region-overlay {
  position: absolute;
  min-width: 12px;
  min-height: 12px;
  border: 2px solid var(--color-accent, #0b7285);
  background: color-mix(in srgb, #0b7285 12%, transparent);
  cursor: pointer;
  padding: 0;
  text-align: left;
}
.region-overlay.selected {
  border-color: #d9480f;
  background: color-mix(in srgb, #d9480f 14%, transparent);
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
  background: #1f2937;
  color: #fff;
  font-size: 11px;
  white-space: nowrap;
}
</style>

<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";

import type { RegionBounds, WorkspaceRegion } from "./types";

const props = defineProps<{
  region: WorkspaceRegion;
  editable: boolean;
  busy?: boolean;
  linkedObjectCount: number;
  sourceLocatorCount: number;
}>();

const emit = defineEmits<{
  save: [payload: { page_number: number; bounds: RegionBounds; rotation: 0 | 90 | 180 | 270 }];
  duplicate: [regionKey: string];
  split: [payload: { first_key: string; second_key: string; first_bounds: RegionBounds; second_bounds: RegionBounds }];
  tombstone: [];
  restore: [];
}>();

const draft = reactive({
  page_number: props.region.page_number,
  x0: props.region.bounds.x0,
  y0: props.region.bounds.y0,
  x1: props.region.bounds.x1,
  y1: props.region.bounds.y1,
  rotation: props.region.rotation,
});
const confirmingTombstone = ref(false);

watch(() => props.region, (region) => {
  Object.assign(draft, {
    page_number: region.page_number,
    x0: region.bounds.x0,
    y0: region.bounds.y0,
    x1: region.bounds.x1,
    y1: region.bounds.y1,
    rotation: region.rotation,
  });
  confirmingTombstone.value = false;
}, { deep: true });

const validation = computed(() => {
  if (!Number.isInteger(draft.page_number) || draft.page_number < 1) return "页码必须是大于 0 的整数。";
  for (const [name, value] of [["x0", draft.x0], ["y0", draft.y0], ["x1", draft.x1], ["y1", draft.y1]] as const) {
    if (!Number.isFinite(value) || value < 0 || value > 1) return `${name} 必须在 0 到 1 之间。`;
  }
  if (draft.x1 <= draft.x0) return "x1 必须大于 x0。";
  if (draft.y1 <= draft.y0) return "y1 必须大于 y0。";
  return "";
});

function bounds(): RegionBounds {
  return { x0: draft.x0, y0: draft.y0, x1: draft.x1, y1: draft.y1 };
}

function save(): void {
  if (!props.editable || props.busy || validation.value) return;
  emit("save", {
    page_number: draft.page_number,
    bounds: bounds(),
    rotation: draft.rotation,
  });
}

function split(): void {
  if (!props.editable || props.busy || validation.value) return;
  const current = bounds();
  const midpoint = Math.round(((current.x0 + current.x1) / 2) * 1_000_000) / 1_000_000;
  emit("split", {
    first_key: `${props.region.region_key}-a`,
    second_key: `${props.region.region_key}-b`,
    first_bounds: { ...current, x1: midpoint },
    second_bounds: { ...current, x0: midpoint },
  });
}
</script>

<template>
  <section class="typed-region-inspector" data-region-inspector aria-label="Region 专用编辑器">
    <header class="typed-inspector-heading">
      <div><p class="eyebrow">PDF REGION</p><h2>{{ region.region_key }}</h2></div>
      <span v-if="region.is_tombstone" class="status-chip is-pending">已移除</span>
    </header>

    <div class="region-context" data-region-context>
      <span>{{ linkedObjectCount }} 个对象</span>
      <span>{{ sourceLocatorCount }} 个来源定位</span>
    </div>

    <label class="form-field">Region key<input class="form-control" :value="region.region_key" readonly></label>
    <div class="region-field-grid">
      <label class="form-field">页码<input v-model.number="draft.page_number" class="form-control" name="page-number" type="number" min="1" :disabled="!editable || busy"></label>
      <label class="form-field">旋转
        <select v-model.number="draft.rotation" class="form-control" name="rotation" :disabled="!editable || busy">
          <option :value="0">0°</option><option :value="90">90°</option><option :value="180">180°</option><option :value="270">270°</option>
        </select>
      </label>
      <label v-for="coordinate in (['x0', 'y0', 'x1', 'y1'] as const)" :key="coordinate" class="form-field">
        {{ coordinate }}
        <input v-model.number="draft[coordinate]" class="form-control" :name="coordinate" type="number" min="0" max="1" step="0.001" :disabled="!editable || busy">
      </label>
    </div>
    <p v-if="validation" class="field-error" data-region-validation role="alert">{{ validation }}</p>

    <div class="typed-inspector-actions">
      <button class="button-primary" data-save-region type="button" :disabled="!editable || busy || Boolean(validation) || region.is_tombstone" @click="save">保存边界</button>
      <button class="button-quiet" data-duplicate-region type="button" :disabled="!editable || busy || region.is_tombstone" @click="emit('duplicate', `${region.region_key}-copy`)">复制</button>
      <button class="button-quiet" data-split-region type="button" :disabled="!editable || busy || Boolean(validation) || region.is_tombstone" @click="split">拆分</button>
      <button v-if="!region.is_tombstone" class="button-quiet danger-action" data-tombstone-region type="button" :disabled="!editable || busy" @click="confirmingTombstone = true">移除</button>
      <button v-else class="button-secondary" data-restore-region type="button" :disabled="!editable || busy" @click="emit('restore')">恢复</button>
    </div>

    <div v-if="confirmingTombstone" class="inline-confirmation" data-tombstone-confirmation role="alert">
      <p>确定从当前草稿移除该 Region？历史 revision 不会被物理删除。</p>
      <button class="button-quiet" type="button" @click="confirmingTombstone = false">取消</button>
      <button class="button-secondary" data-confirm-tombstone type="button" @click="confirmingTombstone = false; emit('tombstone')">确认移除</button>
    </div>
  </section>
</template>

<style scoped>
.typed-region-inspector { display: grid; gap: 14px; }
.typed-inspector-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.typed-inspector-heading h2 { margin: 0; }
.region-context { display: flex; gap: 12px; color: var(--ink-muted); font-size: .7rem; }
.region-field-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.typed-inspector-actions { display: flex; flex-wrap: wrap; gap: 8px; padding-top: 4px; }
.danger-action { color: var(--coral-deep); }
.inline-confirmation { padding: 11px; border: 1px solid var(--coral); background: color-mix(in srgb, var(--coral) 8%, white); }
.inline-confirmation p { margin: 0 0 9px; font-size: .73rem; line-height: 1.5; }
</style>

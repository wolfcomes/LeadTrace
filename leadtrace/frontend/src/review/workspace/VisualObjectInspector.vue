<script setup lang="ts">
import { computed, ref, watch } from "vue";

import CompoundBindings from "../../visual-objects/CompoundBindings.vue";
import ImageBindings from "../../visual-objects/ImageBindings.vue";
import ObjectInspector from "../../visual-objects/ObjectInspector.vue";
import type { MoleculeObjectType, WorkspaceVisualObject } from "./types";

type BindingOperation = "add" | "update" | "remove";

const props = defineProps<{
  visual: WorkspaceVisualObject;
  regions: Array<{ id: string; label: string }>;
  assets: Array<{ id: string; filename: string }>;
  editable: boolean;
  busy?: boolean;
  hasSourceLocator: boolean;
}>();

const emit = defineEmits<{
  save: [payload: { object_type: MoleculeObjectType; label: string | null }];
  "bind-region": [payload: { region_id: string; role: string }];
  "bind-asset": [payload: { asset_id: string; role: string; is_primary: boolean }];
  "bind-compound": [payload: { compound_id: string; label: string; role: string }];
  "remove-binding": [payload: { kind: "regions" | "assets" | "compounds"; id: string }];
  "set-primary-asset": [payload: { id: string; role: string }];
  "locate-source": [regionId: string];
}>();

const objectType = ref<MoleculeObjectType>(props.visual.object_type);
const label = ref(text(props.visual.snapshot.label ?? props.visual.snapshot.display_label));
const regionId = ref(props.visual.region_id ?? props.regions[0]?.id ?? "");
const assetId = ref(props.assets[0]?.id ?? "");
const compoundId = ref("");
const compoundLabel = ref("");

watch(() => props.visual, (visual) => {
  objectType.value = visual.object_type;
  label.value = text(visual.snapshot.label ?? visual.snapshot.display_label);
  regionId.value = visual.region_id ?? props.regions[0]?.id ?? "";
}, { deep: true });

function text(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function operation(value: unknown): BindingOperation | undefined {
  return value === "add" || value === "update" || value === "remove" ? value : undefined;
}

const regionBindings = computed(() => props.visual.bindings.regions.map((binding) => ({
  id: text(binding.id || binding.binding_id || binding.logical_key),
  regionId: text(binding.region_id),
  role: text(binding.role) || "source",
  operation: operation(binding.operation),
})));

const imageBindings = computed(() => props.visual.bindings.assets.map((binding) => {
  const nested = binding.asset && typeof binding.asset === "object" && !Array.isArray(binding.asset)
    ? binding.asset as Record<string, unknown>
    : {};
  return {
    id: text(binding.id || binding.binding_id || binding.logical_key),
    filename: text(nested.original_filename || binding.filename || binding.asset_id),
    objectCount: typeof binding.object_count === "number" ? binding.object_count : 1,
    primary: binding.is_primary === true,
    operation: operation(binding.operation),
    role: text(binding.role) || "image",
  };
}));

const compoundBindings = computed(() => props.visual.bindings.compounds.map((binding) => ({
  id: text(binding.id || binding.binding_id || binding.logical_key),
  compoundId: text(binding.compound_id),
  label: text(binding.label),
  role: text(binding.role) || "label",
  confidence: typeof binding.confidence === "number" ? binding.confidence : null,
  note: text(binding.note) || null,
  operation: operation(binding.operation),
})));

const primaryCrop = computed(() => imageBindings.value.find((binding) => binding.primary));

function save(): void {
  if (!props.editable || props.busy) return;
  emit("save", { object_type: objectType.value, label: label.value.trim() || null });
}
</script>

<template>
  <section class="typed-visual-object-inspector" data-visual-object-inspector aria-label="Visual Object 专用编辑器">
    <ObjectInspector
      :object="{ id: visual.id, objectKey: visual.object_key, objectType, label }"
      :editable="editable && !busy"
      @update-type="objectType = $event as MoleculeObjectType"
      @update-label="label = $event"
    />
    <button class="button-primary" data-save-object type="button" :disabled="!editable || busy" @click="save">保存对象属性</button>

    <button
      v-if="hasSourceLocator && visual.region_id"
      class="source-locator-button button-quiet"
      data-source-locator
      type="button"
      @click="emit('locate-source', visual.region_id!)"
    >定位到 PDF 来源 Region</button>

    <section class="binding-summary" aria-label="Region 绑定">
      <header><h3>Region bindings</h3><span>{{ regionBindings.length }}</span></header>
      <ul v-if="regionBindings.length">
        <li v-for="binding in regionBindings" :key="binding.id" data-region-binding>
          <button type="button" @click="emit('locate-source', binding.regionId)">{{ binding.regionId }}</button>
          <span>{{ binding.role }}</span>
          <span v-if="binding.operation" class="operation-badge status-chip">{{ binding.operation }}</span>
          <button v-if="editable && binding.operation !== 'remove'" class="button-quiet" type="button" @click="emit('remove-binding', { kind: 'regions', id: binding.id })">移除</button>
        </li>
      </ul>
      <p v-else>暂无 Region binding。</p>
      <div class="binding-create-row">
        <select v-model="regionId" class="form-control" aria-label="要绑定的 Region" :disabled="!editable || busy">
          <option v-for="region in regions" :key="region.id" :value="region.id">{{ region.label }}</option>
        </select>
        <button class="button-secondary" type="button" :disabled="!editable || busy || !regionId" @click="emit('bind-region', { region_id: regionId, role: 'source' })">绑定 Region</button>
      </div>
    </section>

    <div v-if="primaryCrop" class="primary-crop-summary" data-primary-crop>主 crop · {{ primaryCrop.filename }}</div>
    <ImageBindings
      :assets="imageBindings"
      :editable="editable && !busy"
      @remove="emit('remove-binding', { kind: 'assets', id: $event })"
      @set-primary="(id) => emit('set-primary-asset', { id, role: imageBindings.find((item) => item.id === id)?.role ?? 'image' })"
    />
    <div class="binding-create-row">
      <select v-model="assetId" class="form-control" aria-label="要绑定的 crop asset" :disabled="!editable || busy">
        <option v-for="asset in assets" :key="asset.id" :value="asset.id">{{ asset.filename }}</option>
      </select>
      <button class="button-secondary" type="button" :disabled="!editable || busy || !assetId" @click="emit('bind-asset', { asset_id: assetId, role: 'crop', is_primary: imageBindings.length === 0 })">绑定 crop</button>
    </div>

    <CompoundBindings
      :bindings="compoundBindings"
      :editable="editable && !busy"
      @remove="emit('remove-binding', { kind: 'compounds', id: $event })"
    />
    <div class="compound-binding-form">
      <input v-model="compoundId" class="form-control" aria-label="Compound ID" placeholder="Compound ID" :disabled="!editable || busy">
      <input v-model="compoundLabel" class="form-control" aria-label="来源标签" placeholder="来源标签" :disabled="!editable || busy">
      <button class="button-secondary" type="button" :disabled="!editable || busy || !compoundId.trim() || !compoundLabel.trim()" @click="emit('bind-compound', { compound_id: compoundId.trim(), label: compoundLabel.trim(), role: 'label' })">绑定 Compound</button>
    </div>
  </section>
</template>

<style scoped>
.typed-visual-object-inspector { display: grid; gap: 14px; }
.typed-visual-object-inspector :deep(.object-inspector),
.typed-visual-object-inspector :deep(.binding-panel) { margin: 0; border: 0; box-shadow: none; }
.source-locator-button { justify-self: start; }
.binding-summary { display: grid; gap: 9px; padding: 14px; border: 1px solid var(--line); }
.binding-summary header { display: flex; justify-content: space-between; }
.binding-summary h3 { margin: 0; font-size: .85rem; }
.binding-summary ul { display: grid; gap: 7px; margin: 0; padding: 0; list-style: none; }
.binding-summary li { display: grid; grid-template-columns: minmax(0, 1fr) auto auto auto; gap: 7px; align-items: center; font-size: .68rem; }
.binding-summary li > button:first-child { overflow: hidden; border: 0; color: var(--teal-deep); background: transparent; text-align: left; text-overflow: ellipsis; cursor: pointer; }
.binding-create-row,
.compound-binding-form { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; }
.compound-binding-form { grid-template-columns: 1fr 1fr; }
.compound-binding-form button { grid-column: 1 / -1; }
.primary-crop-summary { padding: 9px 11px; border-left: 3px solid var(--teal); background: var(--teal-pale); font-size: .72rem; }
</style>

<script setup lang="ts">
import { computed, reactive, watch } from "vue";
import type { ChangesetItem } from "../../api/schema";
import ActivityEditor from "../../activities/ActivityEditor.vue";
import CompoundEditor from "../../compounds/CompoundEditor.vue";
import EvidenceEditor from "../../evidence/EvidenceEditor.vue";
import LineageEditor from "../../lineages/LineageEditor.vue";

const props = defineProps<{
  items: ChangesetItem[];
  editable: boolean;
  reason: string;
}>();

const emit = defineEmits<{
  update: [itemId: string, snapshot: Record<string, unknown>];
}>();

type Snapshot = Record<string, unknown>;

const localSnapshots = reactive<Record<string, Snapshot>>({});

const specializedItems = computed(() => props.items.filter((item) => (
  item.object_kind === "visual_region"
  || item.object_kind === "visual_object"
  || item.object_kind === "molecule_proposal"
  || item.object_kind === "structure"
)));

watch(() => props.items, (items) => {
  for (const item of items) {
    localSnapshots[item.id] = { ...item.proposed_snapshot };
  }
}, { deep: true, immediate: true });

function snapshot(item: ChangesetItem): Snapshot {
  return localSnapshots[item.id] ?? item.proposed_snapshot;
}

function text(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function list(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === "string") : [];
}

function update(item: ChangesetItem, values: Snapshot): void {
  localSnapshots[item.id] = { ...snapshot(item), ...values };
  emit("update", item.id, { ...localSnapshots[item.id] });
}

function compoundModel(item: ChangesetItem) {
  const value = snapshot(item);
  return {
    localIdentity: text(value.local_identity),
    displayLabel: text(value.display_label),
    reason: props.reason,
  };
}

function evidenceModel(item: ChangesetItem) {
  const value = snapshot(item);
  return {
    evidenceKey: text(value.evidence_key),
    originalText: text(value.original_text ?? value.evidence_text),
    sourceLocator: text(value.source_locator),
    compoundIds: list(value.compound_ids),
    reason: props.reason,
  };
}

function activityModel(item: ChangesetItem) {
  const value = snapshot(item);
  return {
    activityKey: text(value.activity_key),
    assay: text(value.assay),
    metric: text(value.metric),
    value: text(value.value),
    unit: text(value.unit),
    qualifier: text(value.qualifier),
    evidenceText: text(value.evidence_text),
    reason: props.reason,
  };
}

function lineageModel(item: ChangesetItem) {
  const value = snapshot(item);
  return {
    lineageKey: text(value.lineage_key ?? value.edge_key),
    parentCompoundId: typeof value.parent_compound_id === "string" ? value.parent_compound_id : null,
    derivedCompoundId: text(value.derived_compound_id),
    relationType: text(value.relation_type),
    relationStatus: text(value.relation_status) || "unresolved",
    evidenceIds: list(value.evidence_ids),
    reason: props.reason,
  };
}

function readiness(item: ChangesetItem) {
  const value = snapshot(item);
  const codes = list(value.blocking_codes);
  return {
    eligible: value.pair_ready === true && codes.length === 0,
    blockingCodes: codes.length ? codes : value.pair_ready === false ? ["PAIR_NOT_READY"] : [],
  };
}

function specializedWorkspaceLink(item: ChangesetItem): string {
  const view = item.object_kind === "visual_region"
    ? "pdf"
    : item.object_kind === "visual_object"
      ? "molecules"
      : "ocsr";
  const parameter = item.object_kind === "visual_region"
    ? "region"
    : item.object_kind === "visual_object"
      ? "object"
      : item.object_kind === "molecule_proposal"
        ? "proposal"
        : "object";
  const suffix = item.object_kind === "structure" ? "" : `&${parameter}=${encodeURIComponent(item.object_id)}`;
  return `/review/changesets/${encodeURIComponent(item.changeset_id)}?view=${view}${suffix}`;
}
</script>

<template>
  <section v-if="items.length" class="scientific-editors" data-scientific-editors aria-label="科学数据编辑器">
    <header class="scientific-heading">
      <div>
        <p class="eyebrow">SCIENTIFIC REVIEW</p>
        <h2>科学数据核查</h2>
      </div>
      <span>{{ items.length }} 个专用编辑器</span>
    </header>
    <div class="scientific-grid">
      <article v-for="item in specializedItems" :key="item.id" class="specialized-handoff panel" data-specialized-handoff>
        <div>
          <p class="eyebrow">SPECIALIZED WORKSPACE</p>
          <h3>{{ item.object_kind === "visual_region" ? "PDF Region" : item.object_kind === "visual_object" ? "Visual Object" : item.object_kind === "molecule_proposal" ? "OCSR Proposal" : "Structure" }}</h3>
          <code>{{ item.object_id }}</code>
        </div>
        <p>此对象必须在 Paper 科学工作台中通过类型化字段、来源 crop 和结构证据核查。</p>
        <a class="button-secondary" :href="specializedWorkspaceLink(item)">打开专用工作台</a>
      </article>
      <CompoundEditor
        v-for="item in items.filter((entry) => entry.object_kind === 'compound')"
        :key="item.id"
        :model-value="compoundModel(item)"
        :editable="editable"
        @update:model-value="update(item, { local_identity: $event.localIdentity, display_label: $event.displayLabel })"
      />
      <EvidenceEditor
        v-for="item in items.filter((entry) => entry.object_kind === 'evidence')"
        :key="item.id"
        :model-value="evidenceModel(item)"
        :editable="editable"
        @update:model-value="update(item, { evidence_key: $event.evidenceKey, original_text: $event.originalText, source_locator: $event.sourceLocator, compound_ids: $event.compoundIds })"
      />
      <ActivityEditor
        v-for="item in items.filter((entry) => entry.object_kind === 'activity')"
        :key="item.id"
        :model-value="activityModel(item)"
        :editable="editable"
        @update:model-value="update(item, { activity_key: $event.activityKey, assay: $event.assay, metric: $event.metric, value: $event.value, unit: $event.unit, qualifier: $event.qualifier, evidence_text: $event.evidenceText })"
      />
      <LineageEditor
        v-for="item in items.filter((entry) => entry.object_kind === 'lineage_edge' || entry.object_kind === 'lineage')"
        :key="item.id"
        :model-value="lineageModel(item)"
        :readiness="readiness(item)"
        :editable="editable"
        @update:model-value="update(item, { lineage_key: $event.lineageKey, edge_key: $event.lineageKey, parent_compound_id: $event.parentCompoundId, derived_compound_id: $event.derivedCompoundId, relation_type: $event.relationType, relation_status: $event.relationStatus, evidence_ids: $event.evidenceIds })"
      />
    </div>
  </section>
</template>

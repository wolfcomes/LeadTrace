<script setup lang="ts">
import { computed } from "vue";

import type { Changeset, RevisionDiff } from "../api/schema";
import StructureComparison from "../structures/StructureComparison.vue";
import PdfReviewCanvas from "../pdf-viewer/PdfReviewCanvas.vue";
import type { PdfRegion } from "../pdf-viewer/RegionOverlay.vue";
import CompoundBindings from "../visual-objects/CompoundBindings.vue";
import ImageBindings from "../visual-objects/ImageBindings.vue";
import type { ScientificEvidence } from "./api";

type Snapshot = Record<string, unknown>;
type SubmittedItem = {
  object_id: string;
  object_kind: string;
  proposed_snapshot?: Snapshot;
};

const props = defineProps<{
  changeset: Changeset;
  diffs: RevisionDiff[];
  evidence: ScientificEvidence | null;
  evidenceStatus: "idle" | "loading" | "ready" | "error";
}>();

const items = computed<SubmittedItem[]>(() => {
  const snapshot = props.changeset.submitted_snapshot;
  const value = snapshot && Array.isArray(snapshot.items) ? snapshot.items : [];
  return value.filter((item): item is SubmittedItem => (
    typeof item === "object"
    && item !== null
    && typeof (item as Record<string, unknown>).object_id === "string"
    && typeof (item as Record<string, unknown>).object_kind === "string"
  ));
});

const itemByObject = computed(() => new Map(items.value.map((item) => [item.object_id, item])));

function snapshotValue(snapshot: Snapshot | undefined, field: string): unknown {
  if (!snapshot) return undefined;
  if (snapshot[field] !== undefined) return snapshot[field];
  const normalized = snapshot.normalized_values;
  return normalized && typeof normalized === "object" && !Array.isArray(normalized)
    ? (normalized as Snapshot)[field]
    : undefined;
}

function changedValue(diff: RevisionDiff, field: string, side: "before" | "after"): unknown {
  const change = diff.changes.find((entry) => entry.path.endsWith(`/${field}`) || entry.path === `/${field}`);
  return change?.[side];
}

const structureComparisons = computed(() => (props.evidence?.structures ?? [])
  .map((entry) => {
    const beforeSmiles = snapshotValue(entry.before, "canonical_smiles");
    const afterSmiles = snapshotValue(entry.after, "canonical_smiles");
    const beforeAsset = snapshotValue(entry.before, "drawing_asset_id");
    const afterAsset = snapshotValue(entry.after, "drawing_asset_id");
    const beforeState = snapshotValue(entry.before, "structure_state");
    const afterState = snapshotValue(entry.after, "structure_state");
    return {
      id: entry.object_id,
      published: {
        label: "发布基线",
        smiles: typeof beforeSmiles === "string" ? beforeSmiles : null,
        imageUrl: typeof beforeAsset === "string" ? `/api/v1/assets/${beforeAsset}/content` : null,
        structureState: typeof beforeState === "string" ? beforeState : undefined,
      },
      draft: {
        label: "提交快照",
        smiles: typeof afterSmiles === "string" ? afterSmiles : null,
        imageUrl: typeof afterAsset === "string" ? `/api/v1/assets/${afterAsset}/content` : null,
        structureState: typeof afterState === "string" ? afterState : undefined,
      },
    };
  }));

function regionFromSnapshot(objectId: string, snapshot: Snapshot): PdfRegion | null {
  const bounds = snapshot.bounds;
  const normalized = bounds && typeof bounds === "object" && !Array.isArray(bounds) ? bounds as Snapshot : snapshot;
  const values = ["x0", "y0", "x1", "y1"].map((field) => Number(normalized[field]));
  if (values.some((value) => !Number.isFinite(value))) return null;
  return {
    id: objectId,
    regionKey: typeof snapshot.region_key === "string" ? snapshot.region_key : objectId,
    pageNumber: Math.max(1, Number(snapshot.page_number) || 1),
    x0: values[0], y0: values[1], x1: values[2], y1: values[3],
    rotation: Number(snapshot.rotation) || 0,
  };
}

const reviewRegions = computed<PdfRegion[]>(() => (props.evidence?.regions ?? [])
  .map((entry) => regionFromSnapshot(entry.object_id, entry.after))
  .filter((region): region is PdfRegion => region !== null));

const bindingDelta = computed<Snapshot>(() => {
  const snapshot = props.changeset.submitted_snapshot;
  return snapshot?.binding_delta && typeof snapshot.binding_delta === "object" && !Array.isArray(snapshot.binding_delta)
    ? snapshot.binding_delta as Snapshot
    : {};
});

function rows(name: string): Snapshot[] {
  const value = bindingDelta.value[name];
  return Array.isArray(value)
    ? value.filter((row): row is Snapshot => typeof row === "object" && row !== null && !Array.isArray(row))
    : [];
}

const pageCount = computed(() => Math.max(1, ...reviewRegions.value.map((region) => region.pageNumber)));
const sourcePdfUrl = computed(() => (
  `/api/v1/papers/${props.changeset.paper_id}/source-pdf?kind=article&release_id=${props.changeset.base_release_id}`
));

const compoundBindings = computed(() => rows("visual_object_compounds").map((row) => ({
  id: String(row.id),
  compoundId: String(row.compound_id),
  label: String(row.label ?? ""),
  role: typeof row.role === "string" ? row.role : undefined,
  confidence: typeof row.confidence === "number" ? row.confidence : null,
  operation: bindingOperation(row.operation),
})));

const imageBindings = computed(() => rows("visual_object_assets").map((row) => ({
  id: String(row.id),
  filename: `Asset ${String(row.asset_id)}`,
  objectCount: 1,
  primary: row.is_primary === true,
  operation: bindingOperation(row.operation),
})));

const regionBindings = computed(() => rows("visual_object_regions"));
const relationBindings = computed(() => rows("visual_object_relations"));

type BindingOperation = "add" | "update" | "remove";
const operationLabels: Record<BindingOperation, string> = {
  add: "新增",
  update: "修改",
  remove: "删除",
};

function bindingOperation(value: unknown): BindingOperation {
  return value === "update" || value === "remove" ? value : "add";
}

function operationLabel(value: unknown): string {
  return operationLabels[bindingOperation(value)];
}

const lineageComparisons = computed(() => props.diffs
  .filter((diff) => diff.object_kind === "lineage" || diff.object_kind === "lineage_edge")
  .map((diff) => ({
    id: diff.object_id,
    before: {
      parent: changedValue(diff, "parent_compound_id", "before") ?? "未设置",
      derived: changedValue(diff, "derived_compound_id", "before") ?? "未设置",
      relation: changedValue(diff, "relation_type", "before") ?? "未设置",
    },
    after: {
      parent: changedValue(diff, "parent_compound_id", "after") ?? snapshotValue(itemByObject.value.get(diff.object_id)?.proposed_snapshot, "parent_compound_id") ?? "未设置",
      derived: changedValue(diff, "derived_compound_id", "after") ?? snapshotValue(itemByObject.value.get(diff.object_id)?.proposed_snapshot, "derived_compound_id") ?? "未设置",
      relation: changedValue(diff, "relation_type", "after") ?? snapshotValue(itemByObject.value.get(diff.object_id)?.proposed_snapshot, "relation_type") ?? "未设置",
    },
  })));

</script>

<template>
  <section class="scientific-approval" data-scientific-approval aria-label="科学核查">
    <header class="section-heading">
      <div>
        <p class="eyebrow">SCIENTIFIC APPROVAL</p>
        <h2>科学核查</h2>
      </div>
      <span>批准前的只读证据视图</span>
    </header>

    <p v-if="evidenceStatus === 'loading'" class="evidence-status" data-evidence-status role="status">正在读取冻结的科学证据…</p>
    <p v-else-if="evidenceStatus === 'error'" class="evidence-status is-error" data-evidence-status role="alert">科学证据未能读取，审批操作已禁用。</p>

    <section v-if="structureComparisons.length" class="review-section" aria-label="结构比较">
      <h3>RDKit 结构比较</h3>
      <div v-for="comparison in structureComparisons" :key="comparison.id" data-structure-comparison>
        <code class="object-id">{{ comparison.id }}</code>
        <StructureComparison :published="comparison.published" :draft="comparison.draft" />
      </div>
    </section>

    <section v-if="reviewRegions.length" class="review-section" aria-label="PDF Region overlay">
      <h3>PDF Region overlay</h3>
      <PdfReviewCanvas
        :pdf-url="sourcePdfUrl"
        :page-count="pageCount"
        :regions="reviewRegions"
        :read-only="true"
      />
    </section>

    <section class="review-section" data-binding-review aria-label="视觉绑定核查">
      <h3>视觉绑定核查</h3>
      <div class="binding-grid">
        <CompoundBindings :bindings="compoundBindings" />
        <ImageBindings :assets="imageBindings" />
        <article class="binding-table">
          <h4>Region 绑定</h4>
          <p v-if="!regionBindings.length" class="empty">无 Region 绑定</p>
          <table v-else><tbody><tr v-for="row in regionBindings" :key="String(row.id)" :class="{ 'is-remove': bindingOperation(row.operation) === 'remove' }"><th>{{ row.visual_object_id }}</th><td>{{ row.region_id }}</td><td><span :class="['operation-badge', `operation-${bindingOperation(row.operation)}`]" data-binding-operation>{{ operationLabel(row.operation) }}</span></td></tr></tbody></table>
        </article>
        <article class="binding-table">
          <h4>对象关系</h4>
          <p v-if="!relationBindings.length" class="empty">无对象关系</p>
          <table v-else><tbody><tr v-for="row in relationBindings" :key="String(row.id)" :class="{ 'is-remove': bindingOperation(row.operation) === 'remove' }"><th>{{ row.source_object_id }}</th><td>{{ row.relation_type }} → {{ row.target_object_id }}</td><td><span :class="['operation-badge', `operation-${bindingOperation(row.operation)}`]" data-binding-operation>{{ operationLabel(row.operation) }}</span></td></tr></tbody></table>
        </article>
      </div>
    </section>

    <section v-if="lineageComparisons.length" class="review-section" data-lineage-comparison aria-label="谱系比较">
      <h3>Lineage 比较</h3>
      <div v-for="entry in lineageComparisons" :key="entry.id" class="lineage-row">
        <code>{{ entry.id }}</code>
        <span>{{ entry.before.parent }} → {{ entry.before.derived }} · {{ entry.before.relation }}</span>
        <strong aria-hidden="true">→</strong>
        <span>{{ entry.after.parent }} → {{ entry.after.derived }} · {{ entry.after.relation }}</span>
      </div>
    </section>
  </section>
</template>

<style scoped>
.scientific-approval { display: grid; gap: 18px; padding: 20px; border: 1px solid var(--line); background: #f8faf8; }
.section-heading { display: flex; justify-content: space-between; gap: 16px; align-items: baseline; }
.section-heading h2, .review-section h3, .binding-table h4 { margin: 0; color: var(--ink-950); font: 600 1.12rem/1.3 Georgia, "Noto Serif SC Variable", serif; }
.section-heading > span { color: var(--ink-500); font-size: .7rem; }
.evidence-status { margin: 0; padding: 10px 12px; border-left: 3px solid var(--line-strong); color: var(--ink-600); background: #fff; font-size: .72rem; }
.evidence-status.is-error { border-color: var(--danger); color: var(--danger); background: #fff6f5; }
.review-section { display: grid; gap: 12px; padding-top: 16px; border-top: 1px solid var(--line); }
.review-section h3 { font-size: .95rem; }
.object-id { color: var(--ink-500); font-size: .62rem; overflow-wrap: anywhere; }
.binding-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.binding-grid :deep(.binding-panel) { height: 100%; box-sizing: border-box; }
.binding-table { display: grid; gap: 8px; padding: 16px; border: 1px solid var(--line); background: #fff; }
.binding-table table { width: 100%; border-collapse: collapse; font-size: .68rem; }
.binding-table th, .binding-table td { padding: 7px; border-top: 1px solid var(--line); text-align: left; overflow-wrap: anywhere; }
.binding-table th { color: var(--ink-600); font-weight: 650; }
.binding-table tr.is-remove { border-left: 3px solid var(--danger); background: #fff3f2; }
.operation-badge { display: inline-flex; min-width: 34px; justify-content: center; padding: 3px 6px; border: 1px solid var(--line-strong); border-radius: 4px; color: var(--ink-700); background: #f5f7f5; font-size: .62rem; font-weight: 750; }
.operation-add { border-color: #8ebaa0; color: var(--forest-800); background: #eef7f1; }
.operation-update { border-color: #c7a85d; color: #715718; background: #fff9e9; }
.operation-remove { border-color: #d99a95; color: var(--danger); background: #fff1f0; }
.empty { margin: 0; color: var(--ink-500); font-size: .7rem; }
.lineage-row { display: grid; grid-template-columns: minmax(100px, .5fr) minmax(0, 1fr) 24px minmax(0, 1fr); gap: 10px; align-items: center; padding: 10px 12px; border: 1px solid var(--line); background: #fff; font-size: .68rem; }
.lineage-row code { color: var(--ink-500); overflow-wrap: anywhere; }
.lineage-row strong { color: var(--gold-700); text-align: center; }
@media (max-width: 760px) { .binding-grid { grid-template-columns: 1fr; } .lineage-row { grid-template-columns: 1fr; } .lineage-row strong { transform: rotate(90deg); } }
</style>

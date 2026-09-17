<script setup lang="ts">
import { computed, ref, watch } from "vue";

import type { Compound, Lineage, LineageEdge } from "../../v2/types";

const props = defineProps<{ lineage: Lineage; compounds: Compound[]; readOnly?: boolean; busy?: boolean }>();
const emit = defineEmits<{
  create: [payload: { parentCompoundId: string; childCompoundId: string; relationType: string; modificationSummary: string | null; reviewStatus: LineageEdge["review_status"] }];
  update: [edge: LineageEdge, payload: { parentCompoundId?: string; childCompoundId?: string; relationType?: string; modificationSummary?: string | null; reviewStatus?: LineageEdge["review_status"] }];
  delete: [edge: LineageEdge];
}>();

const parentId = ref("");
const childId = ref("");
const relationType = ref("lead_optimization");
const modificationSummary = ref("");
const reviewStatus = ref<LineageEdge["review_status"]>("draft");
const editingId = ref<string>();
const editParentId = ref("");
const editChildId = ref("");
const editRelationType = ref("");
const editModificationSummary = ref("");
const editReviewStatus = ref<LineageEdge["review_status"]>("draft");
const memberCompounds = computed(() => {
  const ids = new Set(props.lineage.members.map((member) => member.compound_id));
  return props.compounds.filter((compound) => ids.has(compound.id));
});
const labelById = computed(() => new Map(props.compounds.map((compound) => [compound.id, compound.compound_label])));
const canCreate = computed(() => Boolean(
  parentId.value
  && childId.value
  && parentId.value !== childId.value
  && relationType.value.trim()
  && !props.readOnly
  && !props.busy,
));

watch(memberCompounds, (items) => {
  if (!items.some((item) => item.id === parentId.value)) parentId.value = items[0]?.id ?? "";
  if (!items.some((item) => item.id === childId.value) || childId.value === parentId.value) {
    childId.value = items.find((item) => item.id !== parentId.value)?.id ?? "";
  }
}, { immediate: true });

function create(): void {
  if (!canCreate.value) return;
  emit("create", {
    parentCompoundId: parentId.value,
    childCompoundId: childId.value,
    relationType: relationType.value.trim(),
    modificationSummary: modificationSummary.value.trim() || null,
    reviewStatus: reviewStatus.value,
  });
  modificationSummary.value = "";
  reviewStatus.value = "draft";
}

function startEdit(edge: LineageEdge): void {
  editingId.value = edge.id;
  editParentId.value = edge.parent_compound_id;
  editChildId.value = edge.child_compound_id;
  editRelationType.value = edge.relation_type;
  editModificationSummary.value = edge.modification_summary ?? "";
  editReviewStatus.value = edge.review_status;
}

function cancelEdit(): void {
  editingId.value = undefined;
}

function saveEdit(edge: LineageEdge): void {
  if (!editParentId.value || !editChildId.value || editParentId.value === editChildId.value || !editRelationType.value.trim()) return;
  emit("update", edge, {
    parentCompoundId: editParentId.value,
    childCompoundId: editChildId.value,
    relationType: editRelationType.value.trim(),
    modificationSummary: editModificationSummary.value.trim() || null,
    reviewStatus: editReviewStatus.value,
  });
  cancelEdit();
}
</script>

<template>
  <section class="edge-editor">
    <header class="compact-heading"><div><p class="eyebrow">EDGES</p><h4>直接优化关系</h4></div></header>
    <div v-if="lineage.edges.length" class="edge-list">
      <article v-for="edge in lineage.edges" :key="edge.id" class="edge-row" :class="{ editing: editingId === edge.id }" :data-edge-id="edge.id">
        <template v-if="editingId === edge.id">
          <label class="form-field">Parent<select v-model="editParentId" :disabled="busy"><option v-for="compound in memberCompounds" :key="compound.id" :value="compound.id">{{ compound.compound_label }}</option></select></label>
          <label class="form-field">Child<select v-model="editChildId" :disabled="busy"><option v-for="compound in memberCompounds" :key="compound.id" :value="compound.id">{{ compound.compound_label }}</option></select></label>
          <label class="form-field">Relation<input v-model="editRelationType" data-edit-edge-relation maxlength="128" :disabled="busy"></label>
          <label class="form-field">修改摘要<input v-model="editModificationSummary" data-edit-edge-summary maxlength="10000" :disabled="busy"></label>
          <label class="form-field">审核状态<select v-model="editReviewStatus" :disabled="busy"><option value="draft">Draft</option><option value="reviewer_confirmed">Reviewer confirmed</option><option value="unresolved">Unresolved</option></select></label>
          <div class="editor-actions"><button class="button-primary" data-save-edge-edit type="button" :disabled="busy || !editRelationType.trim() || editParentId === editChildId" @click="saveEdit(edge)">保存 Edge</button><button class="button-quiet" type="button" :disabled="busy" @click="cancelEdit">取消</button></div>
        </template>
        <template v-else>
          <div><strong>{{ labelById.get(edge.parent_compound_id) || "?" }} → {{ labelById.get(edge.child_compound_id) || "?" }}</strong><small>{{ edge.modification_summary || edge.relation_type }}</small></div>
          <label class="form-field">审核状态
          <select :value="edge.review_status" :disabled="readOnly || busy" @change="emit('update', edge, { reviewStatus: ($event.target as HTMLSelectElement).value as LineageEdge['review_status'] })">
            <option value="draft">Draft</option><option value="reviewer_confirmed">Reviewer confirmed</option><option value="unresolved">Unresolved</option>
          </select>
          </label>
          <div class="editor-actions"><button class="button-quiet" data-edit-edge type="button" :disabled="readOnly || busy" @click="startEdit(edge)">编辑</button><button class="button-quiet" data-delete-edge type="button" :disabled="readOnly || busy" @click="emit('delete', edge)">删除 Edge</button></div>
        </template>
      </article>
    </div>
    <p v-else class="workspace-empty-copy">当前 Lineage 尚无 Edge。</p>
    <form class="inline-create-form edge-create-form" @submit.prevent="create">
      <label class="form-field">Parent<select v-model="parentId" :disabled="readOnly || busy"><option v-for="compound in memberCompounds" :key="compound.id" :value="compound.id">{{ compound.compound_label }}</option></select></label>
      <label class="form-field">Child<select v-model="childId" :disabled="readOnly || busy"><option v-for="compound in memberCompounds" :key="compound.id" :value="compound.id">{{ compound.compound_label }}</option></select></label>
      <label class="form-field">Relation<input v-model="relationType" maxlength="128" :disabled="readOnly || busy"></label>
      <label class="form-field">修改摘要<input v-model="modificationSummary" maxlength="10000" :disabled="readOnly || busy"></label>
      <label class="form-field">审核状态<select v-model="reviewStatus" :disabled="readOnly || busy"><option value="draft">Draft</option><option value="reviewer_confirmed">Reviewer confirmed</option><option value="unresolved">Unresolved</option></select></label>
      <button class="button-secondary" type="submit" :disabled="!canCreate">添加 Edge</button>
    </form>
  </section>
</template>

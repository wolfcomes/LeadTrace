<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import { ApiError } from "../../api/client";
import { useAuthStore } from "../../auth/store";
import PdfReviewCanvas from "../../pdf-viewer/PdfReviewCanvas.vue";
import {
  createEvidence,
  createEvidenceLink,
  deleteEvidence,
  deleteEvidenceLink,
  listEvidence,
  listEvidenceLinks,
  listLineages,
  updateEvidence,
} from "../../v2/api";
import type { Evidence, EvidenceLink, LineageEdge, NormalizedBBox, PaperWorkspace } from "../../v2/types";

const props = defineProps<{ workspace: PaperWorkspace; selectedEntityId?: string; readOnly?: boolean }>();
const emit = defineEmits<{ select: [entityId: string]; mutated: [workspaceVersion: number]; conflict: [] }>();
const auth = useAuthStore();
const evidenceItems = ref<Evidence[]>([]);
const edges = ref<LineageEdge[]>([]);
const links = ref<EvidenceLink[]>([]);
const localVersion = ref(props.workspace.version);
const loading = ref(true);
const busy = ref(false);
const showCreate = ref(false);
const showPdf = ref(false);
const kind = ref<Evidence["kind"]>("text");
const pageNumber = ref(1);
const bbox = ref<NormalizedBBox | null>(null);
const quotedText = ref("");
const caption = ref("");
const reviewerNote = ref("");
const selectedEdgeIds = ref<string[]>([]);
const linkRole = ref<EvidenceLink["role"]>("supports");
const linkingEvidenceId = ref<string>();
const linkingEdgeId = ref("");
const editingEvidenceId = ref<string>();
const editEvidenceKind = ref<Evidence["kind"]>("text");
const editEvidencePage = ref(1);
const editEvidenceBBox = ref<NormalizedBBox | null>(null);
const editEvidenceQuote = ref("");
const editEvidenceCaption = ref("");
const editEvidenceNote = ref("");
const error = ref("");

const edgeById = computed(() => new Map(edges.value.map((edge) => [edge.id, edge])));
const evidenceRegions = computed(() => evidenceItems.value.flatMap((item) => item.bbox ? [{
  id: item.id,
  regionKey: item.caption ?? `Evidence p${item.page_number}`,
  pageNumber: item.page_number,
  ...item.bbox,
  rotation: 0,
}] : []));
const editEvidenceHasContent = computed(() => Boolean(
  editEvidenceBBox.value
  || editEvidenceQuote.value.trim()
  || editEvidenceCaption.value.trim(),
));

watch(() => props.workspace.version, (version) => {
  if (version > localVersion.value) localVersion.value = version;
});
watch(() => props.workspace.id, () => { void load(); });
watch(() => props.selectedEntityId, focusAddressedEntity);

function focusAddressedEntity(entityId?: string): void {
  if (!entityId || !edges.value.some((edge) => edge.id === entityId)) return;
  showCreate.value = true;
  selectedEdgeIds.value = [entityId];
}

function mutationError(reason: unknown, fallback: string): void {
  if (reason instanceof ApiError && reason.code === "WORKSPACE_VERSION_CONFLICT") {
    emit("conflict");
    error.value = "Workspace 已更新，正在重新载入全部 Evidence 数据。";
    return;
  }
  error.value = fallback;
}

function edgeLabel(edgeId: string): string {
  const edge = edgeById.value.get(edgeId);
  return edge ? `${edge.parent_compound_id.slice(0, 8)} → ${edge.child_compound_id.slice(0, 8)}` : edgeId.slice(0, 8);
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const [lineageResult, evidenceResult] = await Promise.all([
      listLineages(props.workspace.id),
      listEvidence(props.workspace.id),
    ]);
    edges.value = lineageResult.items.flatMap((lineage) => lineage.edges);
    evidenceItems.value = evidenceResult.items;
    const linkResults = await Promise.all(edges.value.map((edge) => listEvidenceLinks(edge.id)));
    links.value = linkResults.flatMap((result) => result.items);
    localVersion.value = Math.max(
      lineageResult.workspace_version,
      evidenceResult.workspace_version,
      ...linkResults.map((result) => result.workspace_version),
    );
    focusAddressedEntity(props.selectedEntityId);
  } catch {
    error.value = "Evidence 数据暂时无法读取。";
  } finally {
    loading.value = false;
  }
}

function captureRegion(region: { pageNumber: number; x0: number; y0: number; x1: number; y1: number }): void {
  pageNumber.value = region.pageNumber;
  bbox.value = { x0: region.x0, y0: region.y0, x1: region.x1, y1: region.y1 };
  showPdf.value = false;
}

function resetForm(): void {
  kind.value = "text";
  pageNumber.value = 1;
  bbox.value = null;
  quotedText.value = "";
  caption.value = "";
  reviewerNote.value = "";
  selectedEdgeIds.value = [];
  linkRole.value = "supports";
  linkingEvidenceId.value = undefined;
  linkingEdgeId.value = "";
  showPdf.value = false;
  showCreate.value = false;
}

function availableEdges(item: Evidence): LineageEdge[] {
  const linked = new Set(links.value.filter((link) => link.evidence_id === item.id).map((link) => link.edge_id));
  return edges.value.filter((edge) => !linked.has(edge.id));
}

function beginExistingLink(item: Evidence, preferredEdgeId?: string): void {
  const available = availableEdges(item);
  linkingEvidenceId.value = item.id;
  linkingEdgeId.value = available.some((edge) => edge.id === preferredEdgeId)
    ? preferredEdgeId!
    : available[0]?.id ?? "";
  linkRole.value = "supports";
}

function startEvidenceEdit(item: Evidence): void {
  editingEvidenceId.value = item.id;
  editEvidenceKind.value = item.kind;
  editEvidencePage.value = item.page_number;
  editEvidenceBBox.value = item.bbox;
  editEvidenceQuote.value = item.quoted_text ?? "";
  editEvidenceCaption.value = item.caption ?? "";
  editEvidenceNote.value = item.reviewer_note ?? "";
}

function cancelEvidenceEdit(): void {
  editingEvidenceId.value = undefined;
}

async function save(): Promise<void> {
  if (props.readOnly || busy.value || pageNumber.value < 1 || (!quotedText.value.trim() && !bbox.value && !caption.value.trim())) return;
  busy.value = true;
  error.value = "";
  const startingVersion = localVersion.value;
  let createdItem: Evidence | undefined;
  let currentEdgeId: string | undefined;
  try {
    const created = await createEvidence(props.workspace.id, {
      expected_workspace_version: localVersion.value,
      kind: kind.value,
      source_sha256: props.workspace.source.sha256,
      page_number: pageNumber.value,
      bbox: bbox.value,
      quoted_text: quotedText.value.trim() || null,
      caption: caption.value.trim() || null,
      reviewer_note: reviewerNote.value.trim() || null,
    }, auth.csrfToken);
    createdItem = created.evidence;
    evidenceItems.value = [...evidenceItems.value, created.evidence];
    localVersion.value = created.workspace_version;
    for (const edgeId of selectedEdgeIds.value) {
      currentEdgeId = edgeId;
      const linked = await createEvidenceLink(edgeId, {
        expected_workspace_version: localVersion.value,
        evidence_id: created.evidence.id,
        role: linkRole.value,
      }, auth.csrfToken);
      links.value = [...links.value, linked.link];
      localVersion.value = linked.workspace_version;
    }
    resetForm();
    emit("mutated", localVersion.value);
  } catch (reason) {
    if (createdItem) {
      resetForm();
      beginExistingLink(createdItem, currentEdgeId);
      if (reason instanceof ApiError && reason.code === "WORKSPACE_VERSION_CONFLICT") {
        mutationError(reason, "Workspace 已更新；Evidence 已保留，请重新载入后补充 Edge 关联。");
      } else {
        error.value = "Evidence 已保存，但部分 Edge 未关联；请在该 Evidence 卡片继续关联。";
        if (localVersion.value > startingVersion) emit("mutated", localVersion.value);
      }
    } else {
      mutationError(reason, "Evidence 未能保存，请重试。");
    }
  } finally {
    busy.value = false;
  }
}

async function linkExisting(item: Evidence): Promise<void> {
  if (props.readOnly || busy.value || linkingEvidenceId.value !== item.id || !linkingEdgeId.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await createEvidenceLink(linkingEdgeId.value, {
      expected_workspace_version: localVersion.value,
      evidence_id: item.id,
      role: linkRole.value,
    }, auth.csrfToken);
    links.value = [...links.value, result.link];
    localVersion.value = result.workspace_version;
    linkingEvidenceId.value = undefined;
    linkingEdgeId.value = "";
    emit("mutated", result.workspace_version);
  } catch (reason) {
    mutationError(reason, "Evidence 与 Edge 的关联未能保存，请重试。");
  } finally {
    busy.value = false;
  }
}

async function saveEvidenceEdit(item: Evidence): Promise<void> {
  if (props.readOnly || busy.value || editingEvidenceId.value !== item.id || editEvidencePage.value < 1 || !editEvidenceHasContent.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await updateEvidence(item.id, {
      expected_workspace_version: localVersion.value,
      kind: editEvidenceKind.value,
      source_sha256: props.workspace.source.sha256,
      page_number: editEvidencePage.value,
      bbox: editEvidenceBBox.value,
      quoted_text: editEvidenceQuote.value.trim() || null,
      caption: editEvidenceCaption.value.trim() || null,
      reviewer_note: editEvidenceNote.value.trim() || null,
    }, auth.csrfToken);
    evidenceItems.value = evidenceItems.value.map((candidate) => candidate.id === item.id ? result.evidence : candidate);
    localVersion.value = result.workspace_version;
    cancelEvidenceEdit();
    emit("mutated", result.workspace_version);
  } catch (reason) {
    mutationError(reason, "Evidence 修改未能保存，请重试。");
  } finally {
    busy.value = false;
  }
}

async function unlink(link: EvidenceLink): Promise<void> {
  if (props.readOnly || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await deleteEvidenceLink(link.id, localVersion.value, auth.csrfToken);
    links.value = links.value.filter((item) => item.id !== link.id);
    localVersion.value = result.workspace_version;
    emit("mutated", result.workspace_version);
  } catch (reason) {
    mutationError(reason, "Evidence 与 Edge 的关联未能删除。");
  } finally {
    busy.value = false;
  }
}

async function remove(item: Evidence): Promise<void> {
  if (props.readOnly || busy.value || links.value.some((link) => link.evidence_id === item.id)) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await deleteEvidence(item.id, localVersion.value, auth.csrfToken);
    evidenceItems.value = evidenceItems.value.filter((candidate) => candidate.id !== item.id);
    localVersion.value = result.workspace_version;
    emit("mutated", result.workspace_version);
  } catch (reason) {
    mutationError(reason, "Evidence 未能删除；请先解除所有 Edge 关联。");
  } finally {
    busy.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section class="evidence-editor">
    <header class="section-heading"><div><p class="eyebrow">EDGE EVIDENCE</p><h2>证据</h2></div><button class="button-primary" data-add-evidence type="button" :disabled="readOnly || busy" @click="showCreate = !showCreate">添加 Evidence</button></header>
    <form v-if="showCreate" class="evidence-create-form" @submit.prevent="save">
      <div class="inline-create-form">
        <label class="form-field">类型<select v-model="kind" :disabled="readOnly || busy"><option value="text">Text</option><option value="table">Table</option><option value="scheme">Scheme</option><option value="image">Image</option></select></label>
        <label class="form-field">PDF 页码<input v-model.number="pageNumber" data-evidence-page type="number" min="1" :max="workspace.source.page_count" :disabled="readOnly || busy"></label>
        <label class="form-field">Caption<input v-model="caption" maxlength="10000" :disabled="readOnly || busy"></label>
        <button class="button-secondary" type="button" :disabled="readOnly || busy" @click="showPdf = !showPdf">{{ showPdf ? "关闭 PDF" : "从 PDF 框选" }}</button>
      </div>
      <PdfReviewCanvas
        v-if="showPdf"
        :pdf-url="`/api/v2/papers/${workspace.bibliography.paper_id}/source-pdf`"
        :page-count="workspace.source.page_count"
        :page="pageNumber"
        :regions="evidenceRegions"
        :selection-mode="true"
        :allow-rotation="false"
        :read-only="readOnly || busy"
        @create-region="captureRegion"
      />
      <p v-if="bbox" class="selection-summary-line">已框选 p{{ pageNumber }} · {{ bbox.x0.toFixed(3) }}, {{ bbox.y0.toFixed(3) }} → {{ bbox.x1.toFixed(3) }}, {{ bbox.y1.toFixed(3) }}</p>
      <label class="form-field">原文引文<textarea v-model="quotedText" data-evidence-quote rows="3" maxlength="20000" :disabled="readOnly || busy"></textarea></label>
      <label class="form-field">Reviewer note<textarea v-model="reviewerNote" rows="2" maxlength="10000" :disabled="readOnly || busy"></textarea></label>
      <fieldset class="evidence-edge-choices"><legend>关联 Edge（可多选）</legend><label v-for="edge in edges" :key="edge.id"><input v-model="selectedEdgeIds" data-evidence-edge-choice type="checkbox" :value="edge.id" :disabled="readOnly || busy">{{ edgeLabel(edge.id) }} · {{ edge.modification_summary || edge.relation_type }}</label></fieldset>
      <label class="form-field evidence-role-field">关联角色<select v-model="linkRole" :disabled="readOnly || busy"><option value="supports">Supports</option><option value="contradicts">Contradicts</option><option value="contextual">Contextual</option></select></label>
      <div class="editor-actions"><button class="button-primary" data-save-evidence type="button" :disabled="busy || pageNumber < 1 || (!quotedText.trim() && !bbox && !caption.trim())" @click="save">保存 Evidence</button><button class="button-quiet" type="button" :disabled="busy" @click="resetForm">取消</button></div>
    </form>
    <p v-if="error" class="inline-feedback is-error" role="alert">{{ error }}</p>
    <p v-if="loading" class="workspace-empty-copy">正在读取 Evidence…</p>
    <p v-else-if="evidenceItems.length === 0" class="workspace-empty-copy">当前尚无 Evidence。可保存 PDF 引文、表格、Scheme 或图片区域。</p>
    <div v-else class="evidence-card-grid">
      <article v-for="item in evidenceItems" :key="item.id" data-evidence-card :class="{ selected: item.id === selectedEntityId }" @click="emit('select', item.id)">
        <header><span class="status-chip">{{ item.kind }}</span><strong>p{{ item.page_number }}</strong></header>
        <form v-if="editingEvidenceId === item.id" class="evidence-edit-form" @submit.prevent="saveEvidenceEdit(item)" @click.stop>
          <label class="form-field">类型<select v-model="editEvidenceKind" :disabled="busy"><option value="text">Text</option><option value="table">Table</option><option value="scheme">Scheme</option><option value="image">Image</option></select></label>
          <label class="form-field">页码<input v-model.number="editEvidencePage" type="number" min="1" :max="workspace.source.page_count" :disabled="busy"></label>
          <label class="form-field">原文引文<textarea v-model="editEvidenceQuote" data-edit-evidence-quote rows="3" maxlength="20000" :disabled="busy"></textarea></label>
          <label class="form-field">Caption<input v-model="editEvidenceCaption" maxlength="10000" :disabled="busy"></label>
          <label class="form-field">Reviewer note<textarea v-model="editEvidenceNote" rows="2" maxlength="10000" :disabled="busy"></textarea></label>
          <div class="editor-actions"><button class="button-primary" data-save-evidence-edit type="button" :disabled="busy || editEvidencePage < 1 || !editEvidenceHasContent" @click="saveEvidenceEdit(item)">保存修改</button><button class="button-quiet" type="button" :disabled="busy" @click="cancelEvidenceEdit">取消</button></div>
        </form>
        <blockquote v-else-if="item.quoted_text">{{ item.quoted_text }}</blockquote><p v-else>{{ item.caption || "PDF 区域 Evidence" }}</p>
        <small v-if="item.bbox">bbox · {{ item.bbox.x0.toFixed(3) }}, {{ item.bbox.y0.toFixed(3) }} → {{ item.bbox.x1.toFixed(3) }}, {{ item.bbox.y1.toFixed(3) }}</small>
        <div class="evidence-link-list">
          <span v-for="link in links.filter((candidate) => candidate.evidence_id === item.id)" :key="link.id" data-edge-evidence-link><span>{{ edgeLabel(link.edge_id) }} · {{ link.role }}</span><button v-if="!readOnly" class="button-quiet" type="button" :disabled="busy" @click.stop="unlink(link)">解除关联</button></span>
        </div>
        <button v-if="!readOnly && availableEdges(item).length && linkingEvidenceId !== item.id" class="button-secondary" data-link-existing-evidence type="button" :disabled="busy" @click.stop="beginExistingLink(item)">关联更多 Edge</button>
        <form v-if="linkingEvidenceId === item.id" class="existing-evidence-link-form" @submit.prevent="linkExisting(item)" @click.stop>
          <label class="form-field">Edge<select v-model="linkingEdgeId" :disabled="busy"><option v-for="edge in availableEdges(item)" :key="edge.id" :value="edge.id">{{ edgeLabel(edge.id) }} · {{ edge.modification_summary || edge.relation_type }}</option></select></label>
          <label class="form-field">Role<select v-model="linkRole" :disabled="busy"><option value="supports">Supports</option><option value="contradicts">Contradicts</option><option value="contextual">Contextual</option></select></label>
          <button class="button-primary" data-save-existing-link type="button" :disabled="busy || !linkingEdgeId" @click="linkExisting(item)">保存关联</button>
        </form>
        <button v-if="!readOnly && editingEvidenceId !== item.id" class="button-quiet" data-edit-evidence type="button" :disabled="busy" @click.stop="startEvidenceEdit(item)">编辑 Evidence</button>
        <button v-if="!readOnly" class="button-quiet" type="button" :disabled="busy || links.some((link) => link.evidence_id === item.id)" @click.stop="remove(item)">删除 Evidence</button>
      </article>
    </div>
  </section>
</template>

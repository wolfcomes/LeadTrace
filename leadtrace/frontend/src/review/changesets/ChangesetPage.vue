<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch, type WatchStopHandle } from "vue";
import { useRoute } from "vue-router";

import { ApiError } from "../../api/client";
import type { Changeset, ChangesetItem, RevisionDiff } from "../../api/schema";
import { useAuthStore } from "../../auth/store";
import {
  fetchChangeset,
  fetchChangesetDiff,
  fetchChangesetItems,
  reviseChangeset,
  submitChangeset,
  transitionChangeset,
  updateChangeset,
  updateChangesetItem,
} from "../api";
import {
  AutosaveValidationError,
  createAutosave,
  type AutosaveController,
  type AutosaveState,
} from "../autosave";
import ConflictResolver from "../conflicts/ConflictResolver.vue";
import {
  mergeWorkspaceRecovery,
  type RecoveryConflict,
  type RecoveryResolution,
  type WorkspaceRecovery,
  type WorkspaceValues,
} from "../recovery";
import ChangesetDiff from "./ChangesetDiff.vue";
import SubmissionPage from "./SubmissionPage.vue";
import ScientificEditors from "./ScientificEditors.vue";
import PaperWorkspace from "../workspace/PaperWorkspace.vue";
import type { PaperAttestation } from "../workspace/types";

type ViewState = "loading" | "ready" | "not-found" | "error";

type WorkspaceDraft = WorkspaceRecovery;

interface WorkspaceSaveContext {
  generation: number;
  changesetId: string;
  changeset: Changeset;
  items: ChangesetItem[];
}

interface ConflictState {
  expectedVersion?: number;
  currentVersion?: number;
  requestId?: string;
  mergeReady: boolean;
  fields: RecoveryConflict[];
}

const route = useRoute();
const auth = useAuthStore();
const state = ref<ViewState>("loading");
const changeset = ref<Changeset | null>(null);
const items = ref<ChangesetItem[]>([]);
const diffs = ref<RevisionDiff[]>([]);
const title = ref("");
const reason = ref("");
const itemJson = ref<Record<string, string>>({});
const itemErrors = ref<Record<string, string>>({});
const requestId = ref<string>();
const operationBusy = ref(false);
const operationError = ref<string>();
const recoveryRestored = ref(false);
const autosaveState = ref<AutosaveState>("idle");
const conflict = ref<ConflictState | null>(null);
let autosave: AutosaveController<WorkspaceDraft> | undefined;
let stopAutosaveWatch: WatchStopHandle | undefined;
let loadGeneration = 0;
let activeSaveContext: WorkspaceSaveContext | undefined;

const mutable = computed(() => (
  changeset.value !== null
  && ["draft", "revised_draft"].includes(changeset.value.workflow_state)
));

const paperItem = computed(() => items.value.find((item) => item.object_kind === "paper"));
const evidenceItems = computed(() => items.value.filter((item) => item.object_kind === "evidence"));
const scientificItems = computed(() => items.value.filter((item) => {
  if (!["compound", "evidence", "activity", "lineage", "lineage_edge"].includes(item.object_kind)) return false;
  const snapshot = item.proposed_snapshot;
  if (item.object_kind === "compound") return typeof snapshot.local_identity === "string";
  if (item.object_kind === "evidence") return typeof snapshot.evidence_key === "string";
  if (item.object_kind === "activity") return typeof snapshot.activity_key === "string";
  return typeof snapshot.edge_key === "string" || typeof snapshot.lineage_key === "string";
}));

const hasInvalidEditor = computed(() => (
  !title.value.trim()
  || !reason.value.trim()
  || Object.values(itemErrors.value).some(Boolean)
));

const savePending = computed(() => [
  "pending",
  "saving",
  "offline",
  "conflict",
  "error",
].includes(autosaveState.value));

const saveLabels: Record<AutosaveState, string> = {
  idle: "已载入服务端版本",
  pending: "等待自动保存",
  saving: "正在保存",
  saved: "所有修改已保存",
  offline: "离线，修改已保存在本机",
  conflict: "检测到版本冲突",
  error: "保存失败，请检查内容或重试",
};

const stateLabels: Record<Changeset["workflow_state"], string> = {
  draft: "草稿",
  revised_draft: "修订草稿",
  submitted: "待管理员审批",
  changes_requested: "要求修改",
  approved: "已批准",
  published: "已发布",
  superseded: "已被替代",
  rejected: "已拒绝",
};

const objectLabels: Record<string, string> = {
  paper: "文献元数据",
  evidence: "证据文本",
  compound: "化合物",
  structure: "分子结构",
  activity: "活性数据",
  lineage: "优化谱系",
  lineage_edge: "谱系关系",
  visual_region: "图像区域",
  visual_object: "图像对象",
  molecule_proposal: "OCSR 提议",
};

function serverWorkspaceValues(): WorkspaceValues {
  const context = activeSaveContext;
  if (context && isActiveSaveContext(context)) {
    return {
      title: context.changeset.title,
      reason: context.changeset.reason,
      itemJson: Object.fromEntries(context.items.map((item) => [
        item.id,
        JSON.stringify(item.proposed_snapshot, null, 2),
      ])),
    };
  }
  return {
    title: changeset.value?.title ?? title.value,
    reason: changeset.value?.reason ?? reason.value,
    itemJson: Object.fromEntries(items.value.map((item) => [
      item.id,
      JSON.stringify(item.proposed_snapshot, null, 2),
    ])),
  };
}

function workspaceDraft(): WorkspaceDraft {
  return {
    baseVersion: changeset.value?.version ?? 0,
    base: serverWorkspaceValues(),
    title: title.value,
    reason: reason.value,
    itemJson: { ...itemJson.value },
  };
}

function parseSnapshot(raw: string): Record<string, unknown> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new AutosaveValidationError("JSON 格式无效");
  }
  if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new AutosaveValidationError("快照必须是 JSON 对象");
  }
  return parsed as Record<string, unknown>;
}

function validateItem(itemId: string): void {
  try {
    parseSnapshot(itemJson.value[itemId] ?? "");
    itemErrors.value = { ...itemErrors.value, [itemId]: "" };
  } catch (error) {
    itemErrors.value = {
      ...itemErrors.value,
      [itemId]: error instanceof Error ? error.message : "JSON 格式无效",
    };
  }
}

function normalizedValue(item: ChangesetItem, field: string): string {
  try {
    const snapshot = parseSnapshot(itemJson.value[item.id] ?? "");
    const normalized = snapshot.normalized_values;
    if (normalized === null || Array.isArray(normalized) || typeof normalized !== "object") return "";
    const value = (normalized as Record<string, unknown>)[field];
    return typeof value === "string" || typeof value === "number" ? String(value) : "";
  } catch {
    return "";
  }
}

function updateNormalizedValue(item: ChangesetItem, field: string, event: Event): void {
  const target = event.target as HTMLInputElement | HTMLTextAreaElement;
  let snapshot: Record<string, unknown>;
  try {
    snapshot = parseSnapshot(itemJson.value[item.id] ?? "");
  } catch (error) {
    itemErrors.value = {
      ...itemErrors.value,
      [item.id]: error instanceof Error ? error.message : "JSON 格式无效",
    };
    return;
  }

  const current = snapshot.normalized_values;
  const normalized = current !== null && !Array.isArray(current) && typeof current === "object"
    ? { ...current as Record<string, unknown> }
    : {};
  normalized[field] = target.value;
  snapshot.normalized_values = normalized;
  itemJson.value = {
    ...itemJson.value,
    [item.id]: JSON.stringify(snapshot, null, 2),
  };
  validateItem(item.id);
  scheduleSave();
}

function updateScientificSnapshot(itemId: string, snapshot: Record<string, unknown>): void {
  itemJson.value = {
    ...itemJson.value,
    [itemId]: JSON.stringify(snapshot, null, 2),
  };
  validateItem(itemId);
  scheduleSave();
}

function scheduleSave(): void {
  if (!mutable.value || !autosave) return;
  autosave.schedule(workspaceDraft());
}

function isActiveSaveContext(context: WorkspaceSaveContext): boolean {
  return context.generation === loadGeneration
    && changeset.value?.id === context.changesetId;
}

function currentConflict(): ConflictState | null {
  return conflict.value;
}

async function persistWorkspace(
  draft: WorkspaceDraft,
  context: WorkspaceSaveContext,
): Promise<void> {
  const cleanTitle = draft.title.trim();
  const cleanReason = draft.reason.trim();
  if (!cleanTitle || !cleanReason) {
    throw new AutosaveValidationError("标题和修改原因不能为空");
  }
  const parsedSnapshots = new Map<string, Record<string, unknown>>();
  for (const item of context.items) {
    parsedSnapshots.set(item.id, parseSnapshot(draft.itemJson[item.id] ?? ""));
  }

  try {
    if (!isActiveSaveContext(context)) return;
    let currentChangeset = context.changeset;
    if (cleanTitle !== currentChangeset.title || cleanReason !== currentChangeset.reason) {
      currentChangeset = await updateChangeset(context.changesetId, {
        expected_version: currentChangeset.version,
        title: cleanTitle,
        reason: cleanReason,
      });
      if (!isActiveSaveContext(context)) return;
      context.changeset = currentChangeset;
      changeset.value = currentChangeset;
    }
    for (const [index, item] of context.items.entries()) {
      if (!isActiveSaveContext(context)) return;
      const snapshot = parsedSnapshots.get(item.id);
      if (!snapshot || JSON.stringify(snapshot) === JSON.stringify(item.proposed_snapshot)) continue;
      const updated = await updateChangesetItem(context.changesetId, item.id, {
        expected_version: currentChangeset.version,
        proposed_snapshot: snapshot,
      });
      if (!isActiveSaveContext(context)) return;
      context.items[index] = updated;
      currentChangeset = {
        ...currentChangeset,
        version: updated.changeset_version,
        updated_at: new Date().toISOString(),
      };
      context.changeset = currentChangeset;
      items.value = [...context.items];
      changeset.value = currentChangeset;
    }
    if (!isActiveSaveContext(context)) return;
    const refreshedDiffs = await fetchChangesetDiff(context.changesetId);
    if (isActiveSaveContext(context)) {
      diffs.value = refreshedDiffs;
      conflict.value = null;
      operationError.value = undefined;
    }
  } catch (error) {
    if (
      isActiveSaveContext(context)
      && error instanceof ApiError
      && error.code === "REVISION_CONFLICT"
    ) {
      conflict.value = {
        expectedVersion: typeof error.details.expected_version === "number"
          ? error.details.expected_version
          : context.changeset.version,
        currentVersion: typeof error.details.current_version === "number"
          ? error.details.current_version
          : undefined,
        requestId: error.requestId,
        mergeReady: false,
        fields: [],
      };
    }
    throw error;
  }
}

function applyWorkspaceValues(recovery: WorkspaceValues): void {
  if (typeof recovery.title === "string") title.value = recovery.title;
  if (typeof recovery.reason === "string") reason.value = recovery.reason;
  if (recovery.itemJson && typeof recovery.itemJson === "object") {
    for (const item of items.value) {
      const value = recovery.itemJson[item.id];
      if (typeof value === "string") itemJson.value[item.id] = value;
      validateItem(item.id);
    }
  }
  recoveryRestored.value = true;
}

async function fetchStableWorkspace(
  changesetId: string,
  generation: number,
): Promise<[Changeset, ChangesetItem[], RevisionDiff[]] | null> {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const [initialChangeset, itemPayload] = await Promise.all([
      fetchChangeset(changesetId),
      fetchChangesetItems(changesetId),
    ]);
    if (generation !== loadGeneration) return null;
    if (!itemPayload.every((item) => (
      item.changeset_version === initialChangeset.version
    ))) {
      continue;
    }
    const diffPayload = await fetchChangesetDiff(changesetId);
    if (generation !== loadGeneration) return null;
    const verifiedChangeset = await fetchChangeset(changesetId);
    if (generation !== loadGeneration) return null;
    if (initialChangeset.version === verifiedChangeset.version) {
      return [verifiedChangeset, itemPayload, diffPayload];
    }
  }
  throw new Error("Changeset changed repeatedly while loading");
}

async function load(): Promise<void> {
  const generation = ++loadGeneration;
  autosave?.dispose();
  stopAutosaveWatch?.();
  autosave = undefined;
  stopAutosaveWatch = undefined;
  activeSaveContext = undefined;
  autosaveState.value = "idle";
  state.value = "loading";
  operationBusy.value = false;
  operationError.value = undefined;
  conflict.value = null;
  requestId.value = undefined;
  recoveryRestored.value = false;
  const changesetId = String(route.params.changesetId ?? "");
  try {
    const workspace = await fetchStableWorkspace(changesetId, generation);
    if (!workspace) return;
    const [changesetPayload, itemPayload, diffPayload] = workspace;
    changeset.value = changesetPayload;
    items.value = itemPayload;
    diffs.value = diffPayload;
    title.value = changesetPayload.title;
    reason.value = changesetPayload.reason;
    itemJson.value = Object.fromEntries(itemPayload.map((item) => [
      item.id,
      JSON.stringify(item.proposed_snapshot, null, 2),
    ]));
    itemErrors.value = {};
    const saveContext: WorkspaceSaveContext = {
      generation,
      changesetId: changesetPayload.id,
      changeset: changesetPayload,
      items: [...itemPayload],
    };
    activeSaveContext = saveContext;
    autosave = createAutosave({
      key: `${auth.user?.username ?? "unknown-account"}:${changesetPayload.id}`,
      save: (draft) => persistWorkspace(draft, saveContext),
    });
    stopAutosaveWatch = watch(
      autosave.state,
      (value) => {
        autosaveState.value = value;
        if (value === "saved") recoveryRestored.value = false;
      },
      { immediate: true },
    );
    const recovery = autosave.recovery();
    if (mutable.value) {
      if (recovery) {
        if (recovery.baseVersion === changesetPayload.version) {
          applyWorkspaceValues(recovery);
          autosave.schedule(workspaceDraft());
        } else {
          const merge = mergeWorkspaceRecovery(
            recovery,
            serverWorkspaceValues(),
          );
          conflict.value = {
            expectedVersion: Number.isInteger(recovery.baseVersion)
              ? recovery.baseVersion
              : undefined,
            currentVersion: changesetPayload.version,
            mergeReady: true,
            fields: merge.conflicts,
          };
        }
      }
    } else {
      autosave.clearRecovery();
    }
    state.value = "ready";
  } catch (error) {
    if (generation !== loadGeneration) return;
    changeset.value = null;
    items.value = [];
    diffs.value = [];
    if (error instanceof ApiError) {
      requestId.value = error.requestId;
      state.value = error.status === 404 ? "not-found" : "error";
    } else {
      state.value = "error";
    }
  }
}

async function useServerVersion(): Promise<void> {
  autosave?.clearRecovery();
  conflict.value = null;
  await load();
}

async function retryLocalVersion(
  resolutions: Record<string, RecoveryResolution>,
): Promise<void> {
  let recovery = autosave?.recovery();
  if (!recovery) return;
  if (!conflict.value?.mergeReady) {
    conflict.value = null;
    await load();
    recovery = autosave?.recovery();
    if (!recovery || !currentConflict()?.mergeReady) return;
  }
  const merge = mergeWorkspaceRecovery(
    recovery,
    serverWorkspaceValues(),
    resolutions,
  );
  if (!merge.complete) return;
  conflict.value = null;
  applyWorkspaceValues(merge.values);
  autosave?.schedule(workspaceDraft());
}

async function submit(): Promise<void> {
  if (!changeset.value || savePending.value || hasInvalidEditor.value) return;
  const targetId = changeset.value.id;
  const generation = loadGeneration;
  operationBusy.value = true;
  operationError.value = undefined;
  try {
    const updated = await submitChangeset(targetId, changeset.value.version);
    if (generation !== loadGeneration || changeset.value?.id !== targetId) return;
    changeset.value = updated;
    autosave?.clearRecovery();
  } catch (error) {
    if (generation === loadGeneration && changeset.value?.id === targetId) {
      handleOperationError(error);
    }
  } finally {
    if (generation === loadGeneration && changeset.value?.id === targetId) {
      operationBusy.value = false;
    }
  }
}

async function revise(): Promise<void> {
  if (!changeset.value) return;
  const targetId = changeset.value.id;
  const generation = loadGeneration;
  operationBusy.value = true;
  try {
    const updated = await reviseChangeset(targetId, changeset.value.version);
    if (generation !== loadGeneration || changeset.value?.id !== targetId) return;
    changeset.value = updated;
    await load();
  } catch (error) {
    if (generation === loadGeneration && changeset.value?.id === targetId) {
      handleOperationError(error);
    }
  } finally {
    if (generation === loadGeneration && changeset.value?.id === targetId) {
      operationBusy.value = false;
    }
  }
}

async function decide(action: "request-changes" | "approve", decisionReason: string): Promise<void> {
  if (!changeset.value) return;
  const targetId = changeset.value.id;
  const generation = loadGeneration;
  operationBusy.value = true;
  try {
    const updated = await transitionChangeset(targetId, action, {
      expected_version: changeset.value.version,
      reason: decisionReason,
    });
    if (generation !== loadGeneration || changeset.value?.id !== targetId) return;
    changeset.value = updated;
  } catch (error) {
    if (generation === loadGeneration && changeset.value?.id === targetId) {
      handleOperationError(error);
    }
  } finally {
    if (generation === loadGeneration && changeset.value?.id === targetId) {
      operationBusy.value = false;
    }
  }
}

function handleOperationError(error: unknown): void {
  if (error instanceof ApiError && error.code === "REVISION_CONFLICT") {
    conflict.value = {
      expectedVersion: typeof error.details.expected_version === "number"
        ? error.details.expected_version
        : changeset.value?.version,
      currentVersion: typeof error.details.current_version === "number"
        ? error.details.current_version
        : undefined,
      requestId: error.requestId,
      mergeReady: false,
      fields: [],
    };
    return;
  }
  if (error instanceof ApiError && error.code === "BASE_RELEASE_CONFLICT") {
    operationError.value = "发布基线已经变化，请重新载入并创建新的核查草稿。";
    return;
  }
  if (error instanceof ApiError && error.code === "REVIEW_STATE_CONFLICT") {
    operationError.value = "修改集状态已经变化，请重新载入后继续。";
    return;
  }
  operationError.value = "操作未完成，请检查内容或网络连接后重试。";
}

function discardRecovery(): void {
  void useServerVersion();
}

function syncWorkspaceVersion(version: number): void {
  if (!changeset.value || version <= changeset.value.version) return;
  changeset.value = { ...changeset.value, version };
  if (activeSaveContext) activeSaveContext.changeset = changeset.value;
}

function syncPaperAttestation(attestation: PaperAttestation): void {
  if (!changeset.value) return;
  const current = changeset.value;
  const summary = {
    id: attestation.id,
    scope_hash: attestation.scope_hash,
    changeset_version: attestation.changeset_version,
    item_count: attestation.item_count,
    resolved_count: attestation.resolved_count,
    blocker_count: attestation.blocker_count,
    statement: attestation.statement,
  };
  changeset.value = {
    ...current,
    version: attestation.changeset_version,
    validation_results: {
      ...current.validation_results,
      paper_attestation: summary,
    },
  };
  if (activeSaveContext) activeSaveContext.changeset = changeset.value;
}

watch(() => route.params.changesetId, load, { immediate: true });
onBeforeUnmount(() => {
  loadGeneration += 1;
  autosave?.dispose();
  stopAutosaveWatch?.();
});
</script>

<template>
  <div class="review-page changeset-page review-workspace">
    <section v-if="state === 'loading'" class="workspace-state page-state" aria-live="polite">
      <span class="state-spinner" aria-hidden="true"></span>
      <p>正在读取修改集…</p>
    </section>

    <section v-else-if="state === 'not-found'" class="workspace-state page-state">
      <span class="state-symbol" aria-hidden="true">404</span>
      <h1>未找到修改集</h1>
      <p>该修改集不存在，或不属于当前核查任务。</p>
    </section>

    <section v-else-if="state === 'error'" class="workspace-state page-state" role="alert">
      <span class="state-symbol is-error" aria-hidden="true">!</span>
      <h1>暂时无法读取修改集</h1>
      <p>请稍后重试，或将请求编号提供给管理员。</p>
      <small v-if="requestId">请求编号 · {{ requestId }}</small>
      <button class="button-secondary" type="button" @click="load">重新加载</button>
    </section>

    <template v-else-if="changeset">
      <header class="workspace-header page-heading">
        <div>
          <RouterLink class="back-link" to="/review/tasks">← 返回核查任务</RouterLink>
          <p class="eyebrow">CHANGESET WORKSPACE</p>
          <h1>核查修改集</h1>
          <div class="identity-line">
            <code>{{ changeset.id }}</code>
            <span data-changeset-version>版本 {{ changeset.version }}</span>
          </div>
        </div>
        <div class="workspace-status">
          <span class="workflow-state status-chip" :data-state="changeset.workflow_state">
            {{ stateLabels[changeset.workflow_state] }}
          </span>
          <span class="save-state status-chip" :data-save-state="autosaveState">
            <span aria-hidden="true"></span>{{ saveLabels[autosaveState] }}
          </span>
        </div>
      </header>

      <div v-if="recoveryRestored" class="recovery-banner" data-recovery-buffer>
        <div>
          <strong>已恢复本机尚未同步的修改</strong>
          <span>请检查内容，自动保存会在格式有效后继续。</span>
        </div>
        <button type="button" @click="discardRecovery">放弃本机修改</button>
      </div>

      <div v-if="operationError" class="operation-alert" role="alert">{{ operationError }}</div>

      <PaperWorkspace
        :changeset-id="changeset.id"
        :save-state="autosaveState"
        @workspace-updated="syncWorkspaceVersion"
        @attestation-updated="syncPaperAttestation"
      >
        <template #scientific>
      <section class="editor-view" data-editor-view>
        <section class="metadata-editor panel" aria-labelledby="metadata-title">
          <div class="section-heading">
            <div>
              <p class="eyebrow">CHANGE RECORD</p>
              <h2 id="metadata-title">修改集说明</h2>
            </div>
            <span>所有字段均纳入审计记录</span>
          </div>
          <div class="metadata-fields">
            <label for="changeset-title">修改集标题</label>
            <input id="changeset-title" v-model="title" class="form-control" type="text" :readonly="!mutable" maxlength="255" @input="scheduleSave">
            <p v-if="!title.trim()" class="field-error">标题不能为空。</p>
            <label for="changeset-reason">修改原因</label>
            <textarea id="changeset-reason" v-model="reason" class="form-control" rows="4" :readonly="!mutable" maxlength="4000" @input="scheduleSave"></textarea>
            <p v-if="!reason.trim()" class="field-error">修改原因不能为空。</p>
          </div>
        </section>

        <section class="item-section" aria-labelledby="item-title">
          <div class="section-heading">
            <div>
              <p class="eyebrow">VERSIONED OBJECTS</p>
              <h2 id="item-title">修改内容</h2>
            </div>
            <span>{{ items.length }} 个对象</span>
          </div>
          <div class="domain-editors">
            <article v-if="paperItem" class="domain-editor paper-editor panel" data-paper-editor>
              <header>
                <div>
                  <strong>文献元数据</strong>
                  <code>{{ paperItem.object_id }}</code>
                </div>
                <span>#{{ paperItem.sequence }}</span>
              </header>
              <div class="paper-field-grid">
                <div class="field-wide">
                  <label for="paper-title-field">标题</label>
                  <input
                    id="paper-title-field"
                    class="form-control"
                    :value="normalizedValue(paperItem, 'title_guess')"
                    type="text"
                    :readonly="!mutable"
                    @input="updateNormalizedValue(paperItem, 'title_guess', $event)"
                  >
                </div>
                <div>
                  <label for="paper-year-field">发表年份</label>
                  <input
                    id="paper-year-field"
                    class="form-control"
                    :value="normalizedValue(paperItem, 'year')"
                    type="text"
                    inputmode="numeric"
                    :readonly="!mutable"
                    @input="updateNormalizedValue(paperItem, 'year', $event)"
                  >
                </div>
                <div>
                  <label for="paper-target-field">研究靶点</label>
                  <input
                    id="paper-target-field"
                    class="form-control"
                    :value="normalizedValue(paperItem, 'target')"
                    type="text"
                    :readonly="!mutable"
                    @input="updateNormalizedValue(paperItem, 'target', $event)"
                  >
                </div>
                <div>
                  <label>Paper 核查状态</label>
                  <div class="system-owned-field" data-paper-review-status>
                    <strong>{{ normalizedValue(paperItem, "review_status") === "reviewed" ? "已完成 Paper attestation" : "等待 Paper attestation" }}</strong>
                    <small>该状态由 Reviewer attestation 服务端写入，不能作为普通字段编辑。</small>
                  </div>
                </div>
              </div>
            </article>

            <article
              v-for="evidenceItem in evidenceItems"
              :key="evidenceItem.id"
              class="domain-editor evidence-editor panel"
              data-evidence-editor
            >
              <header>
                <div>
                  <strong>证据文本</strong>
                  <code>{{ evidenceItem.object_id }}</code>
                </div>
                <span>#{{ evidenceItem.sequence }}</span>
              </header>
              <label :for="`evidence-text-${evidenceItem.id}`">原文证据</label>
              <textarea
                :id="`evidence-text-${evidenceItem.id}`"
                class="form-control"
                :value="normalizedValue(evidenceItem, 'evidence_text')"
                rows="7"
                :readonly="!mutable"
                @input="updateNormalizedValue(evidenceItem, 'evidence_text', $event)"
              ></textarea>
              <small v-if="normalizedValue(evidenceItem, 'source_locator')">
                来源位置 · {{ normalizedValue(evidenceItem, "source_locator") }}
              </small>
            </article>
          </div>

          <details v-if="items.length" class="advanced-snapshots">
            <summary>系统快照 · 只读</summary>
            <p>完整快照仅用于审计核对。Reviewer 必须使用上方专用字段工作台，系统不会接受通过 JSON 直接编辑。</p>
            <div class="item-editors">
            <article v-for="item in items" :key="item.id" class="item-editor panel" data-item-editor>
              <header>
                <div>
                  <strong>{{ objectLabels[item.object_kind] ?? item.object_kind }}</strong>
                  <code>{{ item.object_id }}</code>
                </div>
                <span>#{{ item.sequence }}</span>
              </header>
              <label :for="`snapshot-${item.id}`">提议快照（只读）</label>
              <textarea
                :id="`snapshot-${item.id}`"
                class="form-control"
                v-model="itemJson[item.id]"
                rows="14"
                spellcheck="false"
                readonly
                @input="validateItem(item.id); scheduleSave()"
              ></textarea>
              <p v-if="itemErrors[item.id]" class="field-error" role="alert">{{ itemErrors[item.id] }}</p>
            </article>
            </div>
          </details>
          <div v-if="items.length === 0" class="empty-items">该修改集尚未添加任何核查内容。</div>
        </section>

        <ScientificEditors
          v-if="scientificItems.length"
          :items="scientificItems"
          :editable="mutable"
          :reason="reason"
          @update="updateScientificSnapshot"
        />
      </section>
        </template>

        <template #diff>
          <ChangesetDiff :diffs="diffs" />
        </template>

        <template #submit="{ attestationCurrent, requiresAttestation }">
          <SubmissionPage
            :changeset="changeset"
            :items="items"
            :diffs="diffs"
            :role="auth.user?.role ?? 'reviewer'"
            :busy="operationBusy"
            :has-invalid-editor="hasInvalidEditor"
            :save-pending="savePending"
            :requires-attestation="requiresAttestation"
            :attestation-current="attestationCurrent"
            @submit="submit"
            @revise="revise"
            @decision="decide"
          />
        </template>
      </PaperWorkspace>
    </template>

    <ConflictResolver
      :open="conflict !== null"
      :expected-version="conflict?.expectedVersion"
      :current-version="conflict?.currentVersion"
      :request-id="conflict?.requestId"
      :merge-ready="conflict?.mergeReady"
      :fields="conflict?.fields"
      @reload="useServerVersion"
      @retry="retryLocalVersion"
    />
  </div>
</template>

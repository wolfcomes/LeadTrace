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

type ViewState = "loading" | "ready" | "not-found" | "error";
type WorkspaceTab = "edit" | "diff" | "submit";

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
const activeTab = ref<WorkspaceTab>("edit");
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
  activeTab.value = "edit";
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
    activeTab.value = "submit";
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

watch(() => route.params.changesetId, load, { immediate: true });
onBeforeUnmount(() => {
  loadGeneration += 1;
  autosave?.dispose();
  stopAutosaveWatch?.();
});
</script>

<template>
  <div class="review-page changeset-page">
    <section v-if="state === 'loading'" class="workspace-state" aria-live="polite">
      <span class="state-spinner" aria-hidden="true"></span>
      <p>正在读取修改集…</p>
    </section>

    <section v-else-if="state === 'not-found'" class="workspace-state">
      <span class="state-symbol" aria-hidden="true">404</span>
      <h1>未找到修改集</h1>
      <p>该修改集不存在，或不属于当前核查任务。</p>
    </section>

    <section v-else-if="state === 'error'" class="workspace-state" role="alert">
      <span class="state-symbol is-error" aria-hidden="true">!</span>
      <h1>暂时无法读取修改集</h1>
      <p>请稍后重试，或将请求编号提供给管理员。</p>
      <small v-if="requestId">请求编号 · {{ requestId }}</small>
      <button class="button-secondary" type="button" @click="load">重新加载</button>
    </section>

    <template v-else-if="changeset">
      <header class="workspace-header">
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
          <span class="workflow-state" :data-state="changeset.workflow_state">
            {{ stateLabels[changeset.workflow_state] }}
          </span>
          <span class="save-state" :data-save-state="autosaveState">
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

      <nav class="workspace-tabs" aria-label="修改集视图">
        <button type="button" :aria-current="activeTab === 'edit' ? 'page' : undefined" @click="activeTab = 'edit'">编辑</button>
        <button type="button" :aria-current="activeTab === 'diff' ? 'page' : undefined" @click="activeTab = 'diff'">变更对比</button>
        <button type="button" :aria-current="activeTab === 'submit' ? 'page' : undefined" @click="activeTab = 'submit'">提交与审批</button>
      </nav>

      <section v-if="activeTab === 'edit'" class="editor-view" data-editor-view>
        <section class="metadata-editor" aria-labelledby="metadata-title">
          <div class="section-heading">
            <div>
              <p class="eyebrow">CHANGE RECORD</p>
              <h2 id="metadata-title">修改集说明</h2>
            </div>
            <span>所有字段均纳入审计记录</span>
          </div>
          <div class="metadata-fields">
            <label for="changeset-title">修改集标题</label>
            <input id="changeset-title" v-model="title" type="text" :readonly="!mutable" maxlength="255" @input="scheduleSave">
            <p v-if="!title.trim()" class="field-error">标题不能为空。</p>
            <label for="changeset-reason">修改原因</label>
            <textarea id="changeset-reason" v-model="reason" rows="4" :readonly="!mutable" maxlength="4000" @input="scheduleSave"></textarea>
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
            <article v-if="paperItem" class="domain-editor paper-editor" data-paper-editor>
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
                    :value="normalizedValue(paperItem, 'target')"
                    type="text"
                    :readonly="!mutable"
                    @input="updateNormalizedValue(paperItem, 'target', $event)"
                  >
                </div>
                <div>
                  <label for="paper-review-status-field">人工核查状态</label>
                  <input
                    id="paper-review-status-field"
                    :value="normalizedValue(paperItem, 'review_status')"
                    type="text"
                    :readonly="!mutable"
                    @input="updateNormalizedValue(paperItem, 'review_status', $event)"
                  >
                </div>
              </div>
            </article>

            <article
              v-for="evidenceItem in evidenceItems"
              :key="evidenceItem.id"
              class="domain-editor evidence-editor"
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
            <summary>高级检查 · 完整 JSON 快照</summary>
            <p>用于核对尚未提供专用表单的字段。修改内容仍通过同一版本与自动保存流程提交。</p>
            <div class="item-editors">
            <article v-for="item in items" :key="item.id" class="item-editor" data-item-editor>
              <header>
                <div>
                  <strong>{{ objectLabels[item.object_kind] ?? item.object_kind }}</strong>
                  <code>{{ item.object_id }}</code>
                </div>
                <span>#{{ item.sequence }}</span>
              </header>
              <label :for="`snapshot-${item.id}`">提议快照</label>
              <textarea
                :id="`snapshot-${item.id}`"
                v-model="itemJson[item.id]"
                rows="14"
                spellcheck="false"
                :readonly="!mutable"
                @input="validateItem(item.id); scheduleSave()"
              ></textarea>
              <p v-if="itemErrors[item.id]" class="field-error" role="alert">{{ itemErrors[item.id] }}</p>
            </article>
            </div>
          </details>
          <div v-if="items.length === 0" class="empty-items">该修改集尚未添加任何核查内容。</div>
        </section>
      </section>

      <ChangesetDiff v-else-if="activeTab === 'diff'" :diffs="diffs" />

      <SubmissionPage
        v-else
        :changeset="changeset"
        :items="items"
        :diffs="diffs"
        :role="auth.user?.role ?? 'reviewer'"
        :busy="operationBusy"
        :has-invalid-editor="hasInvalidEditor"
        :save-pending="savePending"
        @submit="submit"
        @revise="revise"
        @decision="decide"
      />
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

<style scoped>
.review-page { max-width: 1380px; margin: 0 auto; padding: clamp(28px, 5vw, 58px); }
.workspace-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 26px; padding-bottom: 24px; border-bottom: 1px solid var(--line); }
.back-link { display: inline-block; margin-bottom: 23px; color: var(--forest-750); font-size: .72rem; font-weight: 700; text-decoration: none; }
.workspace-header h1 { margin: 0; color: var(--ink-950); font: 600 clamp(2rem, 3vw, 3rem)/1.15 Georgia, "Noto Serif SC Variable", serif; }
.identity-line { display: flex; flex-wrap: wrap; gap: 9px 16px; margin-top: 13px; color: var(--ink-500); font-size: .68rem; }
.identity-line code { user-select: all; }
.workspace-status { display: flex; flex-direction: column; align-items: flex-end; gap: 9px; }
.workflow-state { padding: 6px 10px; border: 1px solid #c6d8ce; color: var(--forest-750); background: var(--forest-100); font-size: .68rem; font-weight: 760; }
.workflow-state[data-state="submitted"] { border-color: #c9d9e1; color: #315f77; background: #edf5f8; }
.workflow-state[data-state="changes_requested"] { border-color: #efcccc; color: var(--danger); background: var(--danger-soft); }
.save-state { display: flex; align-items: center; gap: 7px; color: var(--ink-500); font-size: .67rem; }
.save-state > span { width: 7px; height: 7px; border-radius: 50%; background: #51836a; }
.save-state[data-save-state="pending"] > span, .save-state[data-save-state="saving"] > span { background: #c28a33; }
.save-state[data-save-state="offline"] > span, .save-state[data-save-state="conflict"] > span, .save-state[data-save-state="error"] > span { background: var(--danger); }
.workspace-tabs { display: flex; gap: 0; margin: 27px 0 31px; border-bottom: 1px solid var(--line); }
.workspace-tabs button { min-width: 118px; padding: 12px 15px; border: 0; border-bottom: 3px solid transparent; color: var(--ink-500); background: transparent; font-size: .75rem; font-weight: 700; cursor: pointer; }
.workspace-tabs button[aria-current="page"] { border-bottom-color: var(--forest-750); color: var(--forest-900); }
.editor-view { display: grid; gap: 38px; }
.section-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; margin-bottom: 17px; }
.section-heading h2 { margin: 0; color: var(--ink-950); font: 600 1.4rem/1.2 Georgia, "Noto Serif SC Variable", serif; }
.section-heading > span { color: var(--ink-500); font-size: .7rem; }
.metadata-editor { max-width: 900px; }
.metadata-fields { padding: 22px; border-top: 2px solid var(--forest-900); background: white; box-shadow: var(--shadow-sm); }
.metadata-fields label, .domain-editor label, .item-editor label { display: block; margin: 15px 0 7px; color: var(--ink-650); font-size: .7rem; font-weight: 720; }
.metadata-fields label:first-child { margin-top: 0; }
input, textarea { width: 100%; padding: 11px 12px; border: 1px solid var(--line-strong); border-radius: 5px; color: var(--ink-950); background: #fbfcfb; }
input:focus, textarea:focus { border-color: var(--forest-750); box-shadow: 0 0 0 3px rgba(29,90,71,.08); outline: 0; }
input[readonly], textarea[readonly] { color: var(--ink-650); background: #f2f4f2; cursor: not-allowed; }
.metadata-fields textarea { resize: vertical; line-height: 1.6; }
.domain-editors { display: grid; gap: 16px; }
.domain-editor { min-width: 0; padding: 22px; border: 1px solid var(--line); border-top: 2px solid var(--forest-900); background: white; box-shadow: var(--shadow-sm); }
.domain-editor > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding-bottom: 14px; border-bottom: 1px solid var(--line); }
.domain-editor header strong, .domain-editor header code { display: block; }
.domain-editor header strong { color: var(--ink-800); font-size: .82rem; }
.domain-editor header code { margin-top: 5px; overflow-wrap: anywhere; color: var(--ink-500); font-size: .61rem; }
.domain-editor header > span { color: var(--gold-700); font-size: .67rem; font-weight: 760; }
.paper-field-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0 14px; }
.paper-field-grid .field-wide { grid-column: 1 / -1; }
.evidence-editor textarea { min-height: 138px; resize: vertical; line-height: 1.65; }
.evidence-editor small { display: block; margin-top: 8px; color: var(--ink-500); font-size: .66rem; }
.advanced-snapshots { margin-top: 22px; border-top: 1px solid var(--line); }
.advanced-snapshots > summary { padding: 16px 0; color: var(--forest-750); font-size: .73rem; font-weight: 740; cursor: pointer; }
.advanced-snapshots > p { margin: -4px 0 15px; color: var(--ink-500); font-size: .68rem; line-height: 1.55; }
.item-editors { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.item-editor { min-width: 0; padding: 19px; border: 1px solid var(--line); background: white; box-shadow: var(--shadow-sm); }
.item-editor > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding-bottom: 14px; border-bottom: 1px solid var(--line); }
.item-editor header strong, .item-editor header code { display: block; }
.item-editor header strong { color: var(--ink-800); font-size: .78rem; }
.item-editor header code { margin-top: 5px; overflow-wrap: anywhere; color: var(--ink-500); font-size: .61rem; }
.item-editor header > span { color: var(--gold-700); font-size: .67rem; font-weight: 760; }
.item-editor textarea { resize: vertical; font: .71rem/1.55 ui-monospace, SFMono-Regular, Consolas, monospace; }
.field-error { margin: 6px 0 0; color: var(--danger); font-size: .68rem; }
.recovery-banner, .operation-alert { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-top: 18px; padding: 13px 15px; border-left: 4px solid #c1872e; color: var(--ink-650); background: #fff8e8; font-size: .73rem; }
.recovery-banner strong, .recovery-banner span { display: block; }
.recovery-banner strong { color: var(--ink-800); }
.recovery-banner span { margin-top: 3px; }
.recovery-banner button { flex: 0 0 auto; border: 0; color: var(--forest-750); background: transparent; font-weight: 720; cursor: pointer; }
.operation-alert { border-left-color: var(--danger); color: var(--danger); background: var(--danger-soft); }
.empty-items { padding: 28px; border-top: 2px solid var(--line-strong); color: var(--ink-500); background: white; font-size: .78rem; text-align: center; }
.workspace-state { display: grid; min-height: 520px; place-items: center; align-content: center; gap: 10px; text-align: center; }
.workspace-state h1 { margin: 8px 0 0; color: var(--ink-950); font: 600 1.65rem/1.2 Georgia, "Noto Serif SC Variable", serif; }
.workspace-state p { margin: 0; color: var(--ink-650); font-size: .8rem; }
.workspace-state small { color: var(--ink-500); font-size: .68rem; }
.workspace-state .button-secondary { margin-top: 10px; }
.state-symbol { display: grid; width: 54px; height: 54px; place-items: center; border: 1px solid var(--line-strong); border-radius: 50%; color: var(--forest-750); font: 600 1rem/1 Georgia, serif; }
.state-symbol.is-error { color: var(--danger); }
.state-spinner { width: 27px; height: 27px; border: 3px solid var(--line); border-top-color: var(--forest-750); border-radius: 50%; animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 900px) { .item-editors { grid-template-columns: 1fr; } }
@media (max-width: 650px) { .workspace-header { align-items: flex-start; flex-direction: column; } .workspace-status { align-items: flex-start; } .workspace-tabs { overflow-x: auto; } .workspace-tabs button { min-width: 108px; } .section-heading { align-items: flex-start; flex-direction: column; } .recovery-banner { align-items: flex-start; flex-direction: column; } .paper-field-grid { grid-template-columns: 1fr; } .paper-field-grid .field-wide { grid-column: auto; } }
@media (prefers-reduced-motion: reduce) { .state-spinner { animation: none; } }
</style>

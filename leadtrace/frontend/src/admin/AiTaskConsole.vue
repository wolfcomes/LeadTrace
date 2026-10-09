<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from "vue";
import AiReportOverview from "./AiReportOverview.vue";
import { ApiError } from "../api/client";
import { formatDate, t } from "../i18n";
import {
  archiveResetPaper,
  cancelAiTask,
  changeAiConcurrency,
  createAiTask,
  fetchAiTasks,
  fetchAiReviewReport,
  fetchPaperManagement,
  recallPaper,
  retryAiTask,
  deliverAiTask,
  acceptAiRepair,
  type AiJob,
  type AiReviewReport,
  type AiPreset,
  type AiTaskPage,
  type PaperManagement,
  type StartAiTask,
} from "./aiTasks";

const props = defineProps<{ paperId?: string }>();
const emit = defineEmits<{ changed: [] }>();
const payload = ref<AiTaskPage>();
const management = ref<PaperManagement>();
const loading = ref(true);
const busy = ref(false);
const error = ref("");
const pollError = ref("");
const notice = ref("");
const concurrency = ref(4);
const concurrencyDirty = ref(false);
const producer = ref("");
const producerEffort = ref("");
const reviewer = ref("");
const reviewerEffort = ref("");
const timeoutMinutes = ref(60);
const autoReview = ref(false);
const resetSnapshot = ref<PaperManagement>();
const recallSnapshot = ref<PaperManagement>();
const confirmKey = ref("");
const reports = ref<Record<string, AiReviewReport>>({});
const reportLoading = ref("");
const dialogElement = ref<HTMLElement>();
let previousFocus: HTMLElement | null = null;
const dialogOpen = computed(() =>
  Boolean(resetSnapshot.value || recallSnapshot.value),
);
watch(dialogOpen, async (open) => {
  if (open)
    previousFocus =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
  await nextTick();
  if (open)
    (
      dialogElement.value?.querySelector<HTMLElement>(
        "input, button:not([disabled])",
      ) ?? dialogElement.value
    )?.focus();
  else previousFocus?.focus();
});
function dialogKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape" && !busy.value) {
    event.preventDefault();
    resetSnapshot.value = undefined;
    recallSnapshot.value = undefined;
    return;
  }
  if (event.key !== "Tab" || !dialogElement.value) return;
  const focusable = Array.from(
    dialogElement.value.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  );
  const first = focusable[0],
    last = focusable[focusable.length - 1];
  if (!first) {
    event.preventDefault();
    dialogElement.value.focus();
  } else if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last?.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}
let timer: ReturnType<typeof setTimeout> | undefined;
let generation = 0;
let disposed = false;
const requestKeys = new Map<string, string>();
const presets = computed(() => payload.value?.presets ?? []);
const producerPreset = computed(() =>
  presets.value.find((p) => p.id === producer.value),
);
const reviewerPreset = computed(() =>
  presets.value.find((p) => p.id === reviewer.value),
);
const active = computed(
  () =>
    payload.value?.items.some((j) =>
      [
        "queued",
        "preparing",
        "running",
        "validating",
        "cancel_requested",
      ].includes(j.state),
    ) ?? false,
);
const hasScience = computed(() =>
  Object.entries(management.value?.counts ?? {}).some(
    ([key, value]) =>
      ["compounds", "activities", "lineages", "edges", "evidence"].includes(
        key,
      ) && value > 0,
  ),
);
const modelReady = (p: AiPreset | undefined, effort: string) =>
  Boolean(p?.available && p.efforts.includes(effort));
const validTimeout = computed(
  () =>
    Number.isInteger(timeoutMinutes.value) &&
    timeoutMinutes.value >= 1 &&
    timeoutMinutes.value <= 120,
);
const canGenerate = computed(
  () =>
    !busy.value &&
    !loading.value &&
    !active.value &&
    Boolean(management.value) &&
    !hasScience.value &&
    modelReady(producerPreset.value, producerEffort.value) &&
    validTimeout.value &&
    (!autoReview.value ||
      modelReady(reviewerPreset.value, reviewerEffort.value)),
);
const canReview = computed(
  () =>
    !busy.value &&
    !loading.value &&
    !active.value &&
    Boolean(management.value?.workspace_id) &&
    modelReady(reviewerPreset.value, reviewerEffort.value) &&
    validTimeout.value,
);
const stateLabels: Record<string, string> = {
  proposal_ready: "待接受",
  queued: "排队中",
  preparing: "准备输入",
  running: "模型处理中",
  validating: "程序检查中",
  completed: "运行完成",
  needs_revision: "需要修正",
  partial: "部分完成",
  failed: "失败",
  timed_out: "已超时",
  cancel_requested: "正在停止",
  cancelled: "已取消",
  superseded: "目标已变更",
  coverage_check: "覆盖检查",
  prepared: "输入已准备",
  model_running: "模型处理中",
  stopping: "正在停止",
  interrupted: "运行中断",
  orphaned_process: "正在确认遗留进程",
  configuration_mismatch: "模型配置不一致",
  compound_scope: "化合物覆盖",
  measurement_coverage: "测量数据覆盖",
  activity_semantics: "活性数据语义",
  structure_identity: "结构身份",
  source_crops: "来源截图",
  sar_reasoning: "SAR 关系",
  synthesis_paths: "合成路线",
  unresolved: "尚未解决",
  checked: "已检查",
  not_checked: "尚未检查",
  not_applicable: "不适用",
};
const deliveryLabels: Record<string, string> = {
  pending: "等待写入",
  applied: "已写入草稿",
  conflict: "草稿已变更，未写入",
  not_applicable: "不涉及写入",
  not_applied: "未写入",
};
const countLabels: Record<string, string> = {
  compounds: "Compound",
  activities: "Activity",
  lineages: "Lineage",
  edges: "Edge",
  evidence: "Evidence",
  structures: "结构",
  structure_source_images: "结构来源截图",
  lineage_members: "Lineage 节点",
  lineage_edges: "Edge",
  lineage_presentations: "图布局",
  compound_highlights: "研究起点／论文优选",
  edge_evidence_links: "Edge 与证据关联",
  paper_submissions: "提交记录",
  paper_section_reviews: "区段处置记录",
  change_events: "修改历史",
  workspace_view_receipts: "已读记录",
  ai_tasks: "AI 任务",
  ai_extraction_runs: "历史预填任务",
  ai_provenance: "AI 模型来源记录",
  crop_jobs: "截图任务",
  crop_job_retry_operations: "截图重试记录",
  published_versions: "已发布版本（保留）",
  published_paper_versions: "已发布版本（保留）",
  paper_workspaces: "工作区",
  admin_decisions: "审批记录",
  assets: "附件",
  highlights: "研究起点／论文优选",
  submissions: "提交记录",
  publications: "已发布版本",
  ai_jobs: "AI 任务",
  ai_runs: "AI 运行记录",
  reviews: "复核记录",
  audit_events: "历史事件",
  viewed_items: "已读记录",
  layouts: "图布局",
  article_metadata: "文章信息",
  missing_compounds: "未覆盖 Compound",
  missing_edges: "未覆盖 Edge",
  missing_targets: "未覆盖条目",
  missing_review_targets: "未覆盖条目",
  reviewed_workspace_version: "复核版本",
  invalidated: "目标已失效",
  invalidation_reason: "失效原因",
  candidate_file_sha256: "候选文件 SHA256",
  findings: "发现问题",
  checked: "已检查",
  total: "总数",
  applied_workspace_version: "写入后工作区版本",
  scientific_approval: "科学审核通过",
};
function elapsed(job: AiJob): string {
  if (!job.started_at) return t("尚未开始");
  const seconds = Math.max(
    0,
    Math.floor(
      (Date.parse(job.finished_at ?? new Date().toISOString()) -
        Date.parse(job.started_at)) /
        1000,
    ),
  );
  return t("{minutes} 分 {seconds} 秒", {
    minutes: Math.floor(seconds / 60),
    seconds: seconds % 60,
  });
}
function label(value: string) {
  return t(stateLabels[value] ?? value);
}
function describeError(reason: unknown): string {
  if (reason instanceof ApiError) {
    const detail =
      reason.serverMessage ??
      (typeof reason.details.message === "string"
        ? reason.details.message
        : "");
    return `${t(reason.status === 409 ? "文章或任务状态已变化，请刷新后重试。" : "操作未完成，请检查错误信息后重试。")} ${reason.code}${detail ? ` · ${detail}` : ""}${reason.requestId ? ` · ${t("请求编号")} ${reason.requestId}` : ""}`;
  }
  return t("无法连接服务，请检查网络后重试。");
}
function setPresetDefault(id: string, effort: { value: string }) {
  const p = presets.value.find((item) => item.id === id);
  if (!p?.efforts.includes(effort.value))
    effort.value = p?.default_effort ?? "";
}
watch(producer, () => setPresetDefault(producer.value, producerEffort));
watch(reviewer, () => setPresetDefault(reviewer.value, reviewerEffort));
function selectDefaults() {
  const p = presets.value.find((item) => item.available) ?? presets.value[0];
  if (!producer.value) producer.value = p?.id ?? "";
  if (!reviewer.value) reviewer.value = p?.id ?? "";
  setPresetDefault(producer.value, producerEffort);
  setPresetDefault(reviewer.value, reviewerEffort);
}
async function load(initial = false): Promise<void> {
  const token = generation;
  try {
    const [page, article] = await Promise.all([
      fetchAiTasks(props.paperId),
      props.paperId
        ? fetchPaperManagement(props.paperId)
        : Promise.resolve(undefined),
    ]);
    if (disposed || token !== generation) return;
    payload.value = page;
    management.value = article;
    if (!concurrencyDirty.value)
      concurrency.value = page.settings.max_concurrent;
    selectDefaults();
    pollError.value = "";
  } catch (reason) {
    if (!disposed && token === generation)
      pollError.value = describeError(reason);
  } finally {
    if (!disposed && token === generation) {
      loading.value = false;
      if (initial || !timer) {
        timer = setTimeout(() => {
          timer = undefined;
          void load();
        }, 5000);
      }
    }
  }
}
watch(
  () => props.paperId,
  () => {
    generation++;
    if (timer) clearTimeout(timer);
    timer = undefined;
    payload.value = undefined;
    management.value = undefined;
    loading.value = true;
    resetSnapshot.value = undefined;
    recallSnapshot.value = undefined;
    void load(true);
  },
  { immediate: true },
);
onUnmounted(() => {
  disposed = true;
  generation++;
  if (timer) clearTimeout(timer);
});
async function mutate(
  fn: () => Promise<unknown>,
  success: string,
  changed = false,
) {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    await fn();
    notice.value = t(success);
    await load();
    if (changed) emit("changed");
  } catch (reason) {
    error.value = describeError(reason);
  } finally {
    busy.value = false;
  }
}
function keyFor(signature: string): string {
  let key = requestKeys.get(signature);
  if (!key) {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join(
      "",
    );
    key = [
      hex.slice(0, 8),
      hex.slice(8, 12),
      hex.slice(12, 16),
      hex.slice(16, 20),
      hex.slice(20),
    ].join("-");
    requestKeys.set(signature, key);
  }
  return key;
}
async function start(action: "prefill" | "review") {
  if (
    !props.paperId ||
    !(action === "prefill" ? canGenerate.value : canReview.value)
  )
    return;
  const input: Omit<StartAiTask, "idempotency_key"> = {
    action,
    preset_id: action === "prefill" ? producer.value : reviewer.value,
    reasoning_effort:
      action === "prefill" ? producerEffort.value : reviewerEffort.value,
    timeout_seconds: timeoutMinutes.value * 60,
    expected_workspace_version: management.value?.workspace_version ?? null,
    expected_workspace_id: management.value?.workspace_id ?? null,
    expected_task_version: management.value?.task_version ?? null,
    auto_review:
      action === "prefill" && autoReview.value
        ? { preset_id: reviewer.value, reasoning_effort: reviewerEffort.value }
        : null,
  };
  const signature = JSON.stringify([props.paperId, input]);
  await mutate(async () => {
    await createAiTask(props.paperId!, {
      ...input,
      idempotency_key: keyFor(signature),
    });
    requestKeys.delete(signature);
  }, "AI 任务已进入队列。");
}
function cancel(job: AiJob) {
  void mutate(
    () => cancelAiTask(job.id),
    "已请求取消；运行中的任务将在进程退出后释放名额。",
  );
}
function retry(job: AiJob) {
  void mutate(async () => {
    await retryAiTask(job.id, keyFor(`retry:${job.id}`));
    requestKeys.delete(`retry:${job.id}`);
  }, "新的重试任务已进入队列。");
}
function saveConcurrency() {
  if (
    !Number.isInteger(concurrency.value) ||
    concurrency.value < 1 ||
    concurrency.value > 16
  )
    return;
  void mutate(async () => {
    await changeAiConcurrency(concurrency.value);
    concurrencyDirty.value = false;
  }, "并发设置已保存。");
}
function lifecycleIdentity(snapshot: PaperManagement | undefined) {
  if (
    !snapshot?.workspace_id ||
    snapshot.workspace_version == null ||
    snapshot.task_version == null
  )
    return undefined;
  return {
    expected_workspace_id: snapshot.workspace_id,
    expected_workspace_version: snapshot.workspace_version,
    expected_task_version: snapshot.task_version,
  };
}
function reset() {
  const snapshot = resetSnapshot.value;
  const identity = lifecycleIdentity(snapshot);
  if (
    !props.paperId ||
    !snapshot ||
    !identity ||
    confirmKey.value !== snapshot.paper_key
  )
    return;
  void mutate(
    async () => {
      await archiveResetPaper(props.paperId!, {
        ...identity,
        confirm_paper_key: confirmKey.value,
      });
      resetSnapshot.value = undefined;
      confirmKey.value = "";
    },
    "旧工作内容已归档，新的空白工作区已建立。",
    true,
  );
}
function recall() {
  const snapshot = recallSnapshot.value;
  const identity = lifecycleIdentity(snapshot);
  if (!props.paperId || !identity) return;
  void mutate(
    async () => {
      await recallPaper(props.paperId!, identity);
      recallSnapshot.value = undefined;
    },
    "已收回分配，现有草稿内容保留。",
    true,
  );
}
function paperIsActive(job: AiJob): boolean {
  return payload.value?.items.some(item => item.paper_id === job.paper_id && ['queued', 'preparing', 'running', 'validating', 'cancel_requested'].includes(item.state)) ?? false;
}
async function acceptRepair(job: AiJob) {
  const proposal = reports.value[job.id]?.proposal;
  if (!job.can_accept || !proposal || proposal.total_changes === 0) return;
  await mutate(async () => {
    const result = await acceptAiRepair(job.id, proposal.sha256);
    if (result.delivery_state !== 'applied') throw new ApiError(409, result.error_code ?? 'REPAIR_APPLY_FAILED', '', 'conflict', {}, result.error_message ?? '');
  }, '已接受修补方案并更新草稿，仍需人工审核。', true);
}
async function deliver(job: AiJob) {
  await mutate(async () => {
    const result = await deliverAiTask(job.id);
    if (result.delivery_state !== "applied") throw new ApiError(409, result.error_code ?? "DELIVERY_FAILED", "", "conflict", {}, result.error_message ?? "");
  }, "已导入保存的结果，未重新调用模型。", true);
}
async function viewReport(job: AiJob) {
  if (reportLoading.value) return;
  if (reports.value[job.id]) {
    delete reports.value[job.id];
    return;
  }
  reportLoading.value = job.id;
  error.value = "";
  try {
    reports.value[job.id] = await fetchAiReviewReport(job.id);
  } catch (reason) {
    error.value = describeError(reason);
  } finally {
    reportLoading.value = "";
  }
}
function summary(job: AiJob): [string, string][] {
  return Object.entries(job.result_summary)
    .filter(
      ([, v]) =>
        typeof v === "number" ||
        typeof v === "boolean" ||
        typeof v === "string",
    )
    .filter(
      ([key]) =>
        Object.prototype.hasOwnProperty.call(countLabels, key) && !/(path|token|reasoning|secret|credential|report_available|report_kind|producer_status|proposal_sha256|candidate_file_sha256|source_review_job_id|delivered_saved_result|auto_review_job_id)/i.test(
          key,
        ),
    )
    .map(([key, v]) => [
      t(countLabels[key] ?? key),
      typeof v === "boolean" ? t(v ? "是" : "否") : String(v),
    ]);
}
</script>

<template>
  <section class="ai-task-console" data-ai-task-console>
    <header class="section-heading">
      <div>
        <p class="eyebrow">ADMIN · AI TASKS</p>
        <h2>{{ t(paperId ? "文章管理与 AI 任务" : "AI 任务中心") }}</h2>
        <p>
          {{ t("关闭或刷新网页不会中断任务；运行完成不等于科学审核通过。") }}
        </p>
      </div>
      <button class="button-secondary" :disabled="busy" @click="load()">
        {{ t("刷新状态") }}
      </button>
    </header>
    <p v-if="loading" aria-live="polite">{{ t("正在读取任务…") }}</p>
    <p v-if="pollError" class="inline-feedback is-error" role="alert">
      {{ pollError }}
    </p>
    <p v-if="error" class="inline-feedback is-error" role="alert">
      {{ error }}
    </p>
    <p v-if="notice" class="inline-feedback" role="status">{{ notice }}</p>
    <template v-if="payload">
      <div class="ai-console-health">
        <span
          class="status-chip"
          :data-status="payload.worker.online ? 'verified' : 'failed'"
          >{{
            t(payload.worker.online ? "任务执行服务在线" : "任务执行服务离线")
          }}</span
        ><span>{{
          t("全站并发上限：{count}", { count: payload.settings.max_concurrent })
        }}</span
        ><small v-if="payload.worker.last_seen_at"
          >{{ t("最近心跳") }} ·
          {{ formatDate(payload.worker.last_seen_at) }}</small
        >
      </div>
      <p v-if="!payload.worker.online" class="inline-feedback is-warning">
        {{ t("任务可以排队，执行服务恢复后才会启动。") }}
      </p>
      <form
        v-if="!paperId"
        class="ai-console-settings"
        @submit.prevent="saveConcurrency"
      >
        <label class="form-field"
          >{{ t("全站同时运行的 AI 任务")
          }}<input
            v-model.number="concurrency"
            data-concurrency
            type="number"
            min="1"
            max="16"
            step="1"
            required
            @input="concurrencyDirty = true" /></label
        ><button class="button-primary" :disabled="busy" type="submit">
          {{ t("保存并发设置") }}
        </button>
        <p>
          {{
            t(
              "生成和独立检查共用名额；同一篇文章最多运行一个任务。调低上限不会中止已有任务。",
            )
          }}
        </p>
      </form>
      <template v-if="paperId && management">
        <div class="ai-console-health">
          <strong>{{ management.paper_key }}</strong
          ><span
            >{{ t("当前工作区版本") }} ·
            {{ management.workspace_version ?? t("尚无工作区") }}</span
          ><RouterLink to="/admin/ai-tasks">{{
            t("查看全站队列与并发设置")
          }}</RouterLink>
        </div>
        <div class="ai-console-models">
          <section class="panel">
            <h3>{{ t("首次生成") }}</h3>
            <p>
              {{
                t(
                  "包含有界自检与内部修正。可保存的结果自动写入空白草稿；覆盖缺口和未决问题随报告交付，供人工审核。",
                )
              }}
            </p>
            <label class="form-field"
              >{{ t("生成模型")
              }}<select v-model="producer" data-producer-model :disabled="busy">
                <option
                  v-for="preset in presets"
                  :key="preset.id"
                  :value="preset.id"
                  :disabled="!preset.available"
                >
                  {{ preset.label }} · {{ preset.model
                  }}{{ preset.available ? "" : ` (${t("不可用")})` }}
                </option>
              </select></label
            >
            <p
              v-if="producerPreset?.unavailable_reason"
              class="inline-feedback is-warning"
            >
              {{ producerPreset.unavailable_reason }}
            </p>
            <label class="form-field"
              >{{ t("推理强度")
              }}<select
                v-model="producerEffort"
                data-producer-effort
                :disabled="busy"
              >
                <option
                  v-for="effort in producerPreset?.efforts ?? []"
                  :key="effort"
                  :value="effort"
                >
                  {{ effort }}
                </option>
              </select></label
            ><label class="ai-console-checkbox"
              ><input v-model="autoReview" type="checkbox" :disabled="busy" />{{
                t("生成后自动启动独立检查（使用右侧复核设置）")
              }}</label
            >
            <p v-if="hasScience" class="inline-feedback is-warning">
              {{
                t(
                  "已有科学内容。首次生成需使用空白工作区；如需重做，请先归档并清空。",
                )
              }}
            </p>
            <button
              class="button-primary"
              data-start-prefill
              :disabled="!canGenerate"
              @click="start('prefill')"
            >
              {{ t("启动首次生成") }}
            </button>
          </section>
          <section class="panel">
            <h3>{{ t("新上下文独立检查") }}</h3>
            <p>
              {{
                t(
                  "在一次新上下文任务中复核当前已保存草稿并生成修补方案；使用同一模型和推理强度，接受后才更新草稿。",
                )
              }}
            </p>
            <label class="form-field"
              >{{ t("复核模型")
              }}<select v-model="reviewer" data-review-model :disabled="busy">
                <option
                  v-for="preset in presets"
                  :key="preset.id"
                  :value="preset.id"
                  :disabled="!preset.available"
                >
                  {{ preset.label }} · {{ preset.model
                  }}{{ preset.available ? "" : ` (${t("不可用")})` }}
                </option>
              </select></label
            >
            <p
              v-if="reviewerPreset?.unavailable_reason"
              class="inline-feedback is-warning"
            >
              {{ reviewerPreset.unavailable_reason }}
            </p>
            <label class="form-field"
              >{{ t("推理强度")
              }}<select
                v-model="reviewerEffort"
                data-review-effort
                :disabled="busy"
              >
                <option
                  v-for="effort in reviewerPreset?.efforts ?? []"
                  :key="effort"
                  :value="effort"
                >
                  {{ effort }}
                </option>
              </select></label
            >
            <p>
              {{ t("报告绑定启动时的版本；之后的修改不自动获得复核结论。") }}
            </p>
            <button
              class="button-primary"
              data-start-review
              :disabled="!canReview"
              @click="start('review')"
            >
              {{ t("启动独立检查") }}
            </button>
          </section>
        </div>
        <label class="form-field ai-console-timeout"
          >{{ t("单阶段运行时限（分钟）")
          }}<input
            v-model.number="timeoutMinutes"
            type="number"
            min="1"
            max="120"
            step="1"
            :disabled="busy"
          /><small>{{
            t("1–120 分钟；不同模型的推理档位不能直接比较。")
          }}</small></label
        >
        <p v-if="active" class="inline-feedback">
          {{ t("本篇已有排队或运行中的任务，完成或取消后可再次启动。") }}
        </p>
      </template>
      <section class="ai-console-history">
        <h3>{{ t("任务与历史") }} · {{ payload.total }}</h3>
        <p v-if="!payload.items.length">{{ t("尚无 AI 任务。") }}</p>
        <article
          v-for="job in payload.items"
          :key="job.id"
          class="panel ai-console-job"
          :data-job-id="job.id"
        >
          <header>
            <div>
              <RouterLink v-if="!paperId" :to="`/admin/papers/${job.paper_id}`"
                >{{ job.paper_key }} · {{ job.paper_title }}</RouterLink
              ><strong
                >{{ t(job.action === "repair" ? "修补方案" : job.action === "prefill" ? "首次生成" : "独立检查") }} ·
                {{ job.model }} / {{ job.reasoning_effort }}</strong
              >
            </div>
            <span class="status-chip" :data-status="job.state">{{
              job.delivery_state === "applied" && job.action !== "prefill" ? t("已修改，待审核") : job.action === "prefill" && job.delivery_state === "applied" ? t("已导入，待审核") : label(job.state)
            }}</span>
          </header>
          <p>
            {{ t("当前阶段") }}: {{ label(job.stage) }} ·
            {{ t(deliveryLabels[job.delivery_state] ?? job.delivery_state) }}
          </p>
          <p
            v-if="
              job.action === 'review' &&
              management?.workspace_version !== undefined &&
              job.workspace_version !== management.workspace_version
            "
            class="inline-feedback is-warning"
          >
            {{ t("当前草稿已发生后续修改；本报告仅适用于下方记录的旧版本。") }}
          </p>
          <dl class="ai-console-job-meta">
            <div>
              <dt>{{ t("目标版本") }}</dt>
              <dd>{{ job.workspace_version ?? t("尚无工作区") }}</dd>
            </div>
            <div>
              <dt>{{ t("创建时间") }}</dt>
              <dd>{{ formatDate(job.created_at) }}</dd>
            </div>
            <div v-if="job.started_at">
              <dt>{{ t("开始时间") }}</dt>
              <dd>{{ formatDate(job.started_at) }}</dd>
            </div>
            <div v-if="job.finished_at">
              <dt>{{ t("结束时间") }}</dt>
              <dd>{{ formatDate(job.finished_at) }}</dd>
            </div>
            <div v-if="job.heartbeat_at">
              <dt>{{ t("最近心跳") }}</dt>
              <dd>{{ formatDate(job.heartbeat_at) }}</dd>
            </div>
            <div>
              <dt>{{ t("运行耗时") }}</dt>
              <dd>{{ elapsed(job) }}</dd>
            </div>
            <div>
              <dt>{{ t("任务编号") }}</dt>
              <dd>
                <code>{{ job.id }}</code>
              </dd>
            </div>
            <div>
              <dt>{{ t("尝试次数") }}</dt>
              <dd>{{ job.attempt }}</dd>
            </div>
          </dl>
          <p
            v-if="job.error_code || job.error_message"
            class="inline-feedback is-error"
            role="alert"
          >
            <strong>{{ job.error_code }}</strong> {{ job.error_message }}
          </p>
          <dl v-if="summary(job).length" class="ai-console-job-meta">
            <div v-for="[key, value] in summary(job)" :key="key">
              <dt>{{ key }}</dt>
              <dd>{{ value }}</dd>
            </div>
          </dl>
          <div v-if="reports[job.id]" class="ai-console-report">
            <h4>{{ t(job.action === 'repair' ? '修补方案' : job.action === 'prefill' ? '生成与自检报告' : '独立复核报告') }}</h4>
            <p v-if="job.action === 'prefill'" class="inline-feedback is-warning">{{ t('导入草稿不代表科学审核通过') }}</p>
            <p>{{ t(job.action === 'prefill' ? '写入后工作区版本' : '复核版本') }} · {{ reports[job.id].reviewed_workspace_version }}</p>
            <AiReportOverview :report="reports[job.id]" />
            <template v-if="job.can_accept && reports[job.id].proposal">
              <p class="inline-feedback">{{ t('接受后将把以上修改写入草稿，不重新调用模型。草稿版本已变化时会拒绝写入，保留人工修改。') }}</p>
              <button class="button-primary" data-accept-repair :disabled="busy || paperIsActive(job) || !reports[job.id].proposal?.total_changes" @click="acceptRepair(job)">{{ t('接受全部修改并更新草稿') }}</button>
            </template>
          </div>
          <p v-if="job.can_deliver" class="inline-feedback">{{ t("使用已保存的生成结果，不重新调用模型。导入前会重新检查当前草稿，保留人工修改。") }}</p>
          <div class="ai-console-actions">
            <button v-if="job.can_deliver" class="button-primary" data-deliver-job :disabled="busy" @click="deliver(job)">{{ t("重新导入已生成结果") }}</button>
            <button
              v-if="job.result_summary.report_available"
              class="button-secondary"
              data-view-report
              :disabled="Boolean(reportLoading)"
              @click="viewReport(job)"
            >
              {{ t(job.action === "repair" ? (reports[job.id] ? "收起修补方案" : "查看修补方案") : job.action === "prefill" ? (reports[job.id] ? "收起生成报告" : "查看生成报告") : (reports[job.id] ? "收起复核报告" : "查看复核报告")) }}</button
            ><button
              v-if="job.can_cancel"
              class="button-secondary"
              data-cancel-job
              :disabled="busy"
              @click="cancel(job)"
            >
              {{ t(job.state === "queued" ? "取消排队" : "请求停止") }}</button
            ><button
              v-if="job.can_retry && !job.can_deliver"
              class="button-secondary"
              data-retry-job
              :disabled="busy"
              @click="retry(job)"
            >
              {{ t("重试为新任务") }}
            </button>
          </div>
        </article>
      </section>
      <section v-if="paperId && management" class="panel ai-console-lifecycle">
        <h3>{{ t("分配与归档") }}</h3>
        <p>
          {{
            t(
              "收回只解除分配并保留草稿；归档清空会新建空白工作区。原始 PDF 和已发布版本保留。",
            )
          }}
        </p>
        <div class="ai-console-actions">
          <button
            class="button-secondary"
            data-recall
            :disabled="
              busy ||
              !['assigned', 'changes_requested'].includes(
                management.assignment_state,
              )
            "
            @click="recallSnapshot = management"
          >
            {{ t("收回分配") }}</button
          ><button
            class="button-secondary"
            data-open-reset
            :disabled="
              busy ||
              !management.workspace_id ||
              management.assignment_state === 'submitted'
            "
            @click="
              resetSnapshot = management;
              confirmKey = '';
            "
          >
            {{ t("归档并清空工作区") }}
          </button>
        </div>
        <p
          v-if="management.assignment_state === 'submitted'"
          class="inline-feedback is-warning"
        >
          {{ t("文章正在审批，请先处理提交状态，再收回或归档。") }}
        </p>
        <p>
          {{ t("统一归档目录") }}:
          <code class="ai-console-path">{{ management.archive_root }}</code>
        </p>
        <ul v-if="management.archives.length">
          <li v-for="archive in management.archives" :key="archive.id">
            {{ formatDate(archive.created_at) }} ·
            <code class="ai-console-path">{{ archive.relative_path }}</code>
          </li>
        </ul>
        <p v-else>{{ t("暂无归档。") }}</p>
      </section>
    </template>
    <div
      v-if="resetSnapshot || recallSnapshot"
      class="ai-console-dialog-backdrop"
      @keydown="dialogKeydown"
    >
      <section
        ref="dialogElement"
        class="panel ai-console-dialog"
        role="dialog"
        tabindex="-1"
        aria-modal="true"
        :aria-label="t(resetSnapshot ? '归档并清空工作区' : '收回分配')"
      >
        <template v-if="resetSnapshot"
          ><h2>{{ t("归档并清空工作区") }}</h2>
          <p>
            {{
              t(
                "以下工作内容及历史将归档，当前分配会收回。新建空白工作区后，旧任务结果不能写入新工作区。",
              )
            }}
          </p>
          <dl class="ai-console-job-meta">
            <div v-for="(count, key) in resetSnapshot.counts" :key="key">
              <dt>{{ t(countLabels[key] ?? key) }}</dt>
              <dd>{{ count }}</dd>
            </div>
          </dl>
          <p>
            {{ t("统一归档目录") }}:
            <code class="ai-console-path">{{
              resetSnapshot.archive_root
            }}</code>
          </p>
          <label class="form-field"
            >{{ t("输入文章编号以确认") }}
            <strong>{{ resetSnapshot.paper_key }}</strong
            ><input
              v-model="confirmKey"
              data-reset-paper-key
              autocomplete="off"
              :disabled="busy"
          /></label>
          <p v-if="error" role="alert" class="inline-feedback is-error">
            {{ error }}
          </p>
          <div class="ai-console-actions">
            <button
              class="button-secondary"
              :disabled="busy"
              @click="resetSnapshot = undefined"
            >
              {{ t("取消") }}</button
            ><button
              class="button-primary"
              data-confirm-reset
              :disabled="busy || confirmKey !== resetSnapshot.paper_key"
              @click="reset"
            >
              {{ t("确认归档并新建空白工作区") }}
            </button>
          </div></template
        ><template v-else-if="recallSnapshot"
          ><h2>{{ t("收回分配") }}</h2>
          <p>
            {{
              t(
                "Reviewer 将立即失去本篇编辑权限，现有工作内容保留。重新分配后可继续审核。",
              )
            }}
          </p>
          <p v-if="error" role="alert" class="inline-feedback is-error">
            {{ error }}
          </p>
          <div class="ai-console-actions">
            <button
              class="button-secondary"
              :disabled="busy"
              @click="recallSnapshot = undefined"
            >
              {{ t("取消") }}</button
            ><button
              class="button-primary"
              data-confirm-recall
              :disabled="busy"
              @click="recall"
            >
              {{ t("确认收回") }}
            </button>
          </div></template
        >
      </section>
    </div>
  </section>
</template>

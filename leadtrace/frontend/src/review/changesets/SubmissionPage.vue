<script setup lang="ts">
import { computed, ref } from "vue";

import type { Changeset, ChangesetItem, RevisionDiff, UserRole } from "../../api/schema";

const props = defineProps<{
  changeset: Changeset;
  items: ChangesetItem[];
  diffs: RevisionDiff[];
  role: UserRole;
  busy?: boolean;
  hasInvalidEditor?: boolean;
  savePending?: boolean;
}>();

const emit = defineEmits<{
  submit: [];
  revise: [];
  decision: [action: "request-changes" | "approve", reason: string];
}>();

const decisionReason = ref("");
const decisionError = ref(false);

const domainSummary = computed(() => {
  const counts = new Map<string, number>();
  for (const item of props.items) {
    counts.set(item.object_kind, (counts.get(item.object_kind) ?? 0) + 1);
  }
  return [...counts.entries()];
});

const changedFields = computed(() => props.diffs.reduce(
  (total, entry) => total + entry.changes.length,
  0,
));

const blockers = computed(() => {
  const entries: string[] = [];
  if (!props.changeset.title.trim()) entries.push("修改集标题不能为空");
  if (!props.changeset.reason.trim()) entries.push("修改原因不能为空");
  if (props.items.length === 0) entries.push("至少需要一项修改内容");
  if (changedFields.value === 0) entries.push("当前没有可提交的字段变更");
  if (props.hasInvalidEditor) entries.push("请先修正编辑器中的格式错误");
  if (props.savePending) entries.push("请等待当前草稿保存完成");
  return entries;
});

const canSubmit = computed(() => (
  ["draft", "revised_draft"].includes(props.changeset.workflow_state)
  && blockers.value.length === 0
  && !props.busy
));

const objectLabels: Record<string, string> = {
  paper: "文献元数据",
  compound: "化合物",
  structure: "分子结构",
  evidence: "证据文本",
  activity: "活性数据",
  lineage: "优化谱系",
  lineage_edge: "谱系关系",
  visual_region: "图像区域",
  visual_object: "图像对象",
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

function decide(action: "request-changes" | "approve"): void {
  const reason = decisionReason.value.trim();
  decisionError.value = !reason;
  if (!reason) return;
  emit("decision", action, reason);
}
</script>

<template>
  <section class="submission-view" data-submission-page aria-labelledby="submission-title">
    <div class="section-heading">
      <div>
        <p class="eyebrow">SUBMISSION</p>
        <h2 id="submission-title">提交核查结果</h2>
      </div>
      <span class="state-label" :data-state="changeset.workflow_state">{{ stateLabels[changeset.workflow_state] }}</span>
    </div>

    <div class="submission-layout">
      <div class="submission-main">
        <section class="summary-band" aria-label="修改摘要">
          <div><strong>{{ items.length }}</strong><span>对象</span></div>
          <div><strong>{{ changedFields }}</strong><span>字段变更</span></div>
          <div><strong>{{ domainSummary.length }}</strong><span>数据类别</span></div>
        </section>

        <section class="domain-section">
          <h3>按数据类别汇总</h3>
          <div class="domain-list">
            <div v-for="[kind, count] in domainSummary" :key="kind">
              <span>{{ objectLabels[kind] ?? kind }}</span>
              <strong>{{ count }}</strong>
            </div>
          </div>
        </section>

        <section v-if="changeset.workflow_state === 'submitted'" class="pending-panel" data-approval-state>
          <span aria-hidden="true"></span>
          <div>
            <h3>已提交，等待管理员审批</h3>
            <p>提交快照已经冻结。审批完成或管理员要求修改前，当前内容不可编辑。</p>
          </div>
        </section>

        <section v-else-if="changeset.workflow_state === 'changes_requested'" class="requested-panel" data-approval-state>
          <div>
            <h3>管理员要求修改</h3>
            <p>重新开启草稿后可继续编辑；此前提交记录仍保留在审计历史中。</p>
          </div>
          <button class="button-primary" type="button" :disabled="busy" @click="emit('revise')">重新开启草稿</button>
        </section>

        <section v-if="role === 'admin' && changeset.workflow_state === 'submitted'" class="decision-panel">
          <h3>管理员审批</h3>
          <label for="decision-reason">审批理由</label>
          <textarea id="decision-reason" v-model="decisionReason" rows="4" placeholder="记录批准依据或需要修改的具体内容"></textarea>
          <p v-if="decisionError" class="field-error" role="alert">审批理由不能为空。</p>
          <div class="decision-actions">
            <button class="button-secondary danger-action" type="button" :disabled="busy" @click="decide('request-changes')">要求修改</button>
            <button class="button-primary" type="button" :disabled="busy" @click="decide('approve')">批准修改集</button>
          </div>
        </section>
      </div>

      <aside class="validation-panel">
        <p class="eyebrow">PRE-FLIGHT</p>
        <h3>提交检查</h3>
        <template v-if="blockers.length">
          <p>还有 {{ blockers.length }} 项阻断问题：</p>
          <ul>
            <li v-for="blocker in blockers" :key="blocker">{{ blocker }}</li>
          </ul>
        </template>
        <p v-else class="validation-ready"><span aria-hidden="true">✓</span>当前修改集满足提交条件。</p>
        <button
          v-if="['draft', 'revised_draft'].includes(changeset.workflow_state)"
          class="button-primary submit-button"
          type="button"
          :disabled="!canSubmit"
          @click="emit('submit')"
        >{{ busy ? "正在提交…" : "提交管理员审批" }}</button>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.section-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; margin-bottom: 18px; }
.section-heading h2 { margin: 0; color: var(--ink-950); font: 600 1.4rem/1.2 Georgia, "Noto Serif SC Variable", serif; }
.state-label { padding: 5px 9px; border: 1px solid var(--line); color: var(--ink-650); background: white; font: 700 .64rem/1 "Noto Sans SC Variable", sans-serif; }
.submission-layout { display: grid; grid-template-columns: minmax(0, 1fr) 310px; gap: 22px; align-items: start; }
.submission-main { display: grid; gap: 18px; }
.summary-band { display: grid; grid-template-columns: repeat(3, 1fr); border-top: 2px solid var(--forest-900); background: white; box-shadow: var(--shadow-sm); }
.summary-band div { padding: 20px; border-right: 1px solid var(--line); }
.summary-band div:last-child { border-right: 0; }
.summary-band strong, .summary-band span { display: block; }
.summary-band strong { color: var(--ink-950); font: 600 1.8rem/1 Georgia, "Noto Serif SC Variable", serif; }
.summary-band span { margin-top: 7px; color: var(--ink-500); font-size: .68rem; }
.domain-section, .pending-panel, .requested-panel, .decision-panel, .validation-panel { padding: 22px; border: 1px solid var(--line); background: white; box-shadow: var(--shadow-sm); }
h3 { margin: 0; color: var(--ink-800); font-size: .88rem; }
.domain-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 22px; margin-top: 15px; }
.domain-list div { display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid var(--line); color: var(--ink-650); font-size: .73rem; }
.domain-list strong { color: var(--ink-950); }
.validation-panel { position: sticky; top: 92px; border-top: 3px solid var(--gold-700); }
.validation-panel > p:not(.eyebrow) { color: var(--ink-650); font-size: .75rem; line-height: 1.6; }
.validation-panel ul { margin: 13px 0 0; padding-left: 18px; color: var(--danger); font-size: .72rem; line-height: 1.8; }
.validation-ready { color: var(--forest-750) !important; }
.validation-ready span { margin-right: 5px; font-weight: 800; }
.submit-button { width: 100%; margin-top: 18px; }
.pending-panel, .requested-panel { display: flex; align-items: flex-start; gap: 14px; border-left: 4px solid #4b7993; }
.pending-panel > span { width: 8px; height: 8px; flex: 0 0 8px; margin-top: 4px; border-radius: 50%; background: #4b7993; }
.pending-panel p, .requested-panel p { margin: 8px 0 0; color: var(--ink-650); font-size: .76rem; line-height: 1.65; }
.requested-panel { align-items: center; justify-content: space-between; border-left-color: var(--danger); }
.requested-panel button { flex: 0 0 auto; }
.decision-panel { border-top: 3px solid var(--forest-750); }
.decision-panel label { display: block; margin: 17px 0 7px; color: var(--ink-650); font-size: .72rem; font-weight: 700; }
.decision-panel textarea { width: 100%; resize: vertical; padding: 11px 12px; border: 1px solid var(--line-strong); color: var(--ink-950); background: #fbfcfb; }
.field-error { margin: 7px 0 0; color: var(--danger); font-size: .7rem; }
.decision-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 14px; }
.danger-action { border-color: var(--danger); color: var(--danger); }
@media (max-width: 980px) { .submission-layout { grid-template-columns: 1fr; } .validation-panel { position: static; } }
@media (max-width: 600px) { .summary-band { grid-template-columns: 1fr; } .summary-band div { border-right: 0; border-bottom: 1px solid var(--line); } .domain-list { grid-template-columns: 1fr; } .requested-panel { align-items: stretch; flex-direction: column; } }
</style>

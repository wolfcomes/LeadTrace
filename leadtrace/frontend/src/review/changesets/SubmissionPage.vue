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
  molecule_proposal: "OCSR 提议",
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
      <span class="state-label status-chip" :data-state="changeset.workflow_state">{{ stateLabels[changeset.workflow_state] }}</span>
    </div>

    <div class="submission-layout">
      <div class="submission-main">
        <section class="summary-band panel" aria-label="修改摘要">
          <div><strong>{{ items.length }}</strong><span>对象</span></div>
          <div><strong>{{ changedFields }}</strong><span>字段变更</span></div>
          <div><strong>{{ domainSummary.length }}</strong><span>数据类别</span></div>
        </section>

        <section class="domain-section panel">
          <h3>按数据类别汇总</h3>
          <div class="domain-list">
            <div v-for="[kind, count] in domainSummary" :key="kind">
              <span>{{ objectLabels[kind] ?? kind }}</span>
              <strong>{{ count }}</strong>
            </div>
          </div>
        </section>

        <section v-if="changeset.workflow_state === 'submitted'" class="pending-panel panel" data-approval-state>
          <span aria-hidden="true"></span>
          <div>
            <h3>已提交，等待管理员审批</h3>
            <p>提交快照已经冻结。审批完成或管理员要求修改前，当前内容不可编辑。</p>
          </div>
        </section>

        <section v-else-if="changeset.workflow_state === 'changes_requested'" class="requested-panel panel" data-approval-state>
          <div>
            <h3>管理员要求修改</h3>
            <p>重新开启草稿后可继续编辑；此前提交记录仍保留在审计历史中。</p>
          </div>
          <button class="button-primary" type="button" :disabled="busy" @click="emit('revise')">重新开启草稿</button>
        </section>

        <section v-if="role === 'admin' && changeset.workflow_state === 'submitted'" class="decision-panel panel">
          <h3>管理员审批</h3>
          <label for="decision-reason">审批理由</label>
          <textarea id="decision-reason" v-model="decisionReason" class="form-control" rows="4" placeholder="记录批准依据或需要修改的具体内容"></textarea>
          <p v-if="decisionError" class="field-error" role="alert">审批理由不能为空。</p>
          <div class="decision-actions">
            <button class="button-secondary danger-action" type="button" :disabled="busy" @click="decide('request-changes')">要求修改</button>
            <button class="button-primary" type="button" :disabled="busy" @click="decide('approve')">批准修改集</button>
          </div>
        </section>
      </div>

      <aside class="validation-panel panel">
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

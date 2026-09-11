<script setup lang="ts">
import { computed } from "vue";

import type { RevisionDiff } from "../../api/schema";

const props = defineProps<{ diffs: RevisionDiff[] }>();

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

const categoryLabels: Record<string, string> = {
  scalar: "字段",
  text: "文本",
  smiles: "SMILES",
  binding: "绑定",
  lineage_endpoint: "谱系端点",
  region_coordinate: "区域坐标",
  collection: "集合",
  lifecycle: "生命周期",
};

const fieldLabels: Record<string, string> = {
  title: "标题",
  title_guess: "标题",
  evidence_text: "证据文本",
  canonical_smiles: "Canonical SMILES",
  activity_metric: "活性指标",
  activity_value: "活性数值",
  activity_unit: "活性单位",
  relation_type: "关系类型",
  relation_status: "关系状态",
  parent_entity_id: "母体编号",
  derived_entity_id: "衍生物编号",
};

const changedDiffs = computed(() => props.diffs.filter((entry) => entry.changes.length > 0));

function fieldLabel(path: string): string {
  const leaf = path.split("/").filter(Boolean).at(-1) ?? path;
  return fieldLabels[leaf] ?? leaf.replaceAll("_", " ");
}

function categoryLabel(category: string): string {
  return categoryLabels[category] ?? category;
}

function formatValue(value: unknown, present: boolean): string {
  if (!present) return "未设置";
  if (value === null) return "空值";
  if (typeof value === "string") return value || "空字符串";
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value);
}
</script>

<template>
  <section class="diff-view" data-diff-summary aria-labelledby="diff-title">
    <div class="section-heading">
      <div>
        <p class="eyebrow">STRUCTURED DIFF</p>
        <h2 id="diff-title">结构化变更</h2>
      </div>
      <span>{{ changedDiffs.reduce((total, entry) => total + entry.changes.length, 0) }} 项字段变更</span>
    </div>

    <div v-if="changedDiffs.length" class="diff-groups">
      <article v-for="entry in changedDiffs" :key="entry.object_id" class="diff-group">
        <header>
          <div>
            <span>{{ objectLabels[entry.object_kind] ?? entry.object_kind }}</span>
            <code>{{ entry.object_id }}</code>
          </div>
          <strong>{{ entry.change_type === "create" ? "新增" : entry.change_type === "tombstone" ? "移除" : "修订" }}</strong>
        </header>
        <div class="change-list">
          <div v-for="change in entry.changes" :key="change.path" class="change-row">
            <div class="change-field">
              <strong>{{ fieldLabel(change.path) }}</strong>
              <span>{{ categoryLabel(change.category) }}</span>
              <code>{{ change.path }}</code>
            </div>
            <div class="value before-value">
              <span>发布基线</span>
              <pre>{{ formatValue(change.before, change.before_present) }}</pre>
            </div>
            <div class="change-arrow" aria-hidden="true">→</div>
            <div class="value after-value">
              <span>当前草稿</span>
              <pre>{{ formatValue(change.after, change.after_present) }}</pre>
            </div>
          </div>
        </div>
      </article>
    </div>

    <div v-else class="empty-diff">
      <span aria-hidden="true">—</span>
      <p>当前修改集没有可提交的字段变更。</p>
    </div>
  </section>
</template>

<style scoped>
.section-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; margin-bottom: 18px; }
.section-heading h2 { margin: 0; color: var(--ink-950); font: 600 1.4rem/1.2 Georgia, "Noto Serif SC Variable", serif; }
.section-heading > span { color: var(--ink-500); font-size: .72rem; }
.diff-groups { display: grid; gap: 18px; }
.diff-group { border: 1px solid var(--line); background: white; box-shadow: var(--shadow-sm); }
.diff-group > header { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 16px 18px; border-bottom: 1px solid var(--line); background: #f8faf8; }
.diff-group header span, .diff-group header code { display: block; }
.diff-group header span { color: var(--ink-800); font-size: .78rem; font-weight: 760; }
.diff-group header code { margin-top: 4px; color: var(--ink-500); font-size: .62rem; }
.diff-group header > strong { color: var(--forest-750); font-size: .7rem; }
.change-row { display: grid; grid-template-columns: minmax(135px, .65fr) minmax(0, 1fr) 24px minmax(0, 1fr); gap: 14px; align-items: stretch; padding: 17px 18px; border-bottom: 1px solid var(--line); }
.change-row:last-child { border-bottom: 0; }
.change-field { min-width: 0; padding-top: 4px; }
.change-field strong, .change-field span, .change-field code { display: block; }
.change-field strong { color: var(--ink-800); font-size: .78rem; }
.change-field span { margin-top: 5px; color: var(--gold-700); font-size: .65rem; font-weight: 700; }
.change-field code { margin-top: 9px; overflow-wrap: anywhere; color: var(--ink-500); font-size: .58rem; }
.value { min-width: 0; padding: 11px 13px; border-left: 3px solid var(--line-strong); background: #f7f8f7; }
.value > span { color: var(--ink-500); font-size: .61rem; font-weight: 750; }
.value pre { max-height: 180px; margin: 8px 0 0; overflow: auto; color: var(--ink-800); font: .7rem/1.55 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
.after-value { border-left-color: #4e8b6b; background: #f1f7f3; }
.change-arrow { align-self: center; color: var(--gold-700); text-align: center; }
.empty-diff { display: grid; min-height: 190px; place-items: center; align-content: center; gap: 10px; border-top: 2px solid var(--line-strong); color: var(--ink-500); background: white; }
.empty-diff span { font: 600 1.4rem/1 Georgia, serif; }
.empty-diff p { margin: 0; font-size: .8rem; }
@media (max-width: 860px) { .change-row { grid-template-columns: 1fr; } .change-arrow { transform: rotate(90deg); } .section-heading { align-items: flex-start; flex-direction: column; } }
</style>

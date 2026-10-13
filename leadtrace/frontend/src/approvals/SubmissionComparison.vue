<script setup lang="ts">
import { computed } from "vue";
import { t } from "../i18n";
import { statusLabel } from "../i18n/status";
import { buildComparison, compoundLabel, edgeLabel, rows, type Comparison, type Row } from "./comparison";
import FrozenEvidence from "./FrozenEvidence.vue";
const props = defineProps<{ snapshot: Record<string, unknown>; comparison?: Comparison; paperId: string }>();
const result = computed(() => buildComparison(props.snapshot, props.comparison));
const baseline = computed(() => props.comparison?.baseline_snapshot ?? {});
const domainLabels: Record<string, string> = {paper: "文章信息", source: "原文来源", sections: "区段状态", compounds: "化合物", structures: "结构", structure_source_images: "结构证据", lineages: "Lineage", lineage_members: "Lineage 成员", lineage_edges: "关系", evidence: "证据", edge_evidence_links: "证据关联", activities: "活性", compound_highlights: "关键化合物"};
const fieldLabels: Record<string, string> = {
  compound_label: "化合物编号", display_name: "名称", description: "说明", sort_order: "排序", status: "状态", review_status: "核对状态", review_hint: "核对提示", smiles: "SMILES", canonical_smiles: "Canonical SMILES", molfile: "Molfile", inchi: "InChI", inchikey: "InChIKey", compound_id: "化合物", lineage_id: "Lineage", lineage_label: "Lineage 名称", lineage_type: "Lineage 类型", parent_compound_id: "起始化合物", child_compound_id: "衍生化合物", relation_type: "关系类型", modification_summary: "结构变化说明", edge_id: "关系", evidence_id: "证据", role: "作用", assay_name: "实验名称", metric: "指标", operator: "比较符号", value: "数值", unit: "单位", context: "实验条件", kind: "证据类型", page_number: "页码", x0: "左边界", y0: "上边界", x1: "右边界", y1: "下边界", quoted_text: "原文摘录", caption: "标题", reviewer_note: "核对说明", source_context: "原文位置", label: "标签", source_sha256: "原文指纹", state: "区段状态", note: "说明", section_key: "区段", title: "文章标题", journal: "期刊", doi: "DOI", publication_year: "年份", volume: "卷", issue: "期", sha256: "原文指纹", page_count: "页数", source_key: "原文路径", source_root_key: "原文目录", asset_id: "原文文件", paper_key: "文章编号", reason: "原因", highlight_type: "标记类型", scope: "适用范围", rationale: "选择依据", abstract: "摘要", abstract_source: "摘要来源", pdb_references: "PDB 结构引用",
};
const stateLabels: Record<string, string> = { draft: "待确认", reviewer_confirmed: "已确认", unresolved: "未解决", not_reported: "原文未报告", completed: "已完成", pending: "待确认", needs_revision: "待修改", needs_review: "待核对", root: "起点", intermediate: "中间节点", terminal: "终点", supports: "支持", contradicts: "反驳", context: "上下文", study_start: "研究起点", paper_selected: "论文优选", unspecified: "待分类", sar: "SAR / 结构优化", synthesis: "化学合成" };
function reviewState(value: unknown): string { return stateLabels[String(value)] ? t(stateLabels[String(value)]) : statusLabel(value); }
function valueLabel(key: string, value: unknown, snapshot: Record<string, unknown>): string {
  if (value === undefined || value === null || value === "") return "—";
  if (["compound_id", "parent_compound_id", "child_compound_id"].includes(key)) return compoundLabel(snapshot, value);
  if (key === "edge_id") return edgeLabel(snapshot, value);
  if (key === "lineage_id") return String(rows(snapshot, "lineages").find(row => row.id === value)?.lineage_label ?? value);
  if (key === "evidence_id") {
    const row = rows(snapshot, "evidence").find(row => row.id === value);
    return row ? `${row.caption || t("证据")} · ${t("第 {page} 页", {page: Number(row.page_number)})}` : String(value);
  }
  if (["status", "review_status", "state", "role", "lineage_type"].includes(key)) return reviewState(value);
  if (Array.isArray(value)) return value.map(item => item && typeof item === "object" ? Object.entries(item).map(([name, entry]) => `${name}: ${entry ?? "—"}`).join("; ") : String(item)).join("\n");
  if (typeof value === "object") return Object.entries(value).map(([name, item]) => `${name}: ${String(item)}`).join("; ");
  return String(value);
}
function depiction(row: Row | null): string | undefined { return row?.depiction_asset_id ? `/api/v1/assets/${encodeURIComponent(String(row.depiction_asset_id))}/content` : undefined; }
const counts = computed(() => Object.entries(domainLabels).map(([key, label]) => ({key, label, count: result.value.changes.filter(change => change.domain === key).length})).filter(row => row.count));
</script>
<template>
  <section class="submission-comparison panel" data-comparison-summary>
    <div class="section-heading"><div><p class="eyebrow">SUBMISSION CHANGES</p><h2>{{ t("本次提交修改") }}</h2></div></div>
    <p v-if="comparison?.kind === 'previous_submission' && result.available">{{ t("比较起点：第 {number} 次提交", {number: comparison.baseline_submission_number ?? '—'}) }}</p>
    <p v-else-if="comparison?.kind === 'reviewer_start' && result.available">{{ t("比较起点：Reviewer 开始本轮审核时的内容") }}</p>
    <p class="comparison-explainer">{{ t("展示起点与冻结提交之间的净变化；完整提交仍是批准对象。") }}</p>
    <p v-for="warning in result.warnings" :key="warning" class="message is-error" role="alert" data-comparison-warning>{{ t(warning) }}</p>
    <div v-if="result.available" class="comparison-counts">
      <strong>{{ t("{count} 项实质修改", {count: result.changes.length}) }}</strong>
      <span v-for="count in counts" :key="count.key">{{ t(count.label) }} {{ count.count }}</span>
      <span>{{ t("新增 {added} · 删除 {removed} · 问题处理 {resolved}", {added: result.changes.filter(row => row.kind === 'added').length, removed: result.changes.filter(row => row.kind === 'removed').length, resolved: result.changes.filter(row => row.issueResolution).length}) }}</span>
    </div>
    <section v-if="result.issues.length" class="remaining-issues" data-remaining-issues>
      <h3>{{ t("仍需核对的问题") }} · {{ result.issues.length }}</h3>
      <ul><li v-for="(issue, index) in result.issues" :key="index"><strong>{{ t(domainLabels[issue.domain] ?? issue.domain) }} · {{ t(issue.label) }}</strong> — {{ reviewState(issue.detail) }}</li></ul>
    </section>
    <p v-if="result.available && !result.changes.length" class="section-empty" data-no-scientific-changes>{{ t("本次没有实质内容修改。请结合未解决问题及完整提交决定是否批准。") }}</p>
    <section v-for="group in result.groups" :key="group.label" class="change-group">
      <h3>{{ t(group.label) }}</h3>
      <article v-for="change in group.changes" :key="`${change.domain}-${change.id}`" class="change-card" data-change-card :data-entity-type="change.domain" :data-entity-id="change.id">
        <header><strong>{{ t(domainLabels[change.domain] ?? change.domain) }} · {{ t(change.label) }}</strong><span class="change-kind" :class="change.kind">{{ t(change.kind === 'added' ? '新增' : change.kind === 'removed' ? '删除' : '修改') }}</span><span v-if="change.issueResolution" class="status-chip">{{ t("问题处理") }}</span></header>
        <p class="change-actors">{{ t("修改来源") }}: {{ change.actors.length ? change.actors.map(actor => actor === 'ai' ? 'AI' : actor === 'reviewer' ? 'Reviewer' : actor === 'admin' ? 'Admin' : 'System').join(' · ') : t('未记录') }}</p>
        <div v-if="change.domain === 'structures'" class="comparison-pair structure-pair">
          <div><h4>{{ t("修改前") }}</h4><img v-if="depiction(change.before)" :src="depiction(change.before)" :alt="t('修改前结构')"><code>{{ change.before?.canonical_smiles || change.before?.smiles || '—' }}</code></div>
          <div><h4>{{ t("修改后") }}</h4><img v-if="depiction(change.after)" :src="depiction(change.after)" :alt="t('修改后结构')"><code>{{ change.after?.canonical_smiles || change.after?.smiles || '—' }}</code></div>
        </div>
        <div class="change-fields-wrap"><table class="change-fields"><thead><tr><th>{{ t("字段") }}</th><th>{{ t("修改前") }}</th><th>{{ t("修改后") }}</th></tr></thead><tbody><tr v-for="field in change.fields" :key="field.key"><th>{{ t(fieldLabels[field.key] ?? field.key) }}</th><td class="before-value">{{ valueLabel(field.key, field.before, baseline) }}</td><td class="after-value">{{ valueLabel(field.key, field.after, snapshot) }}</td></tr></tbody></table></div>
        <div v-if="change.evidenceBefore.length || change.evidenceAfter.length" class="comparison-pair evidence-pair">
          <div><h4>{{ t("修改前证据") }}</h4><FrozenEvidence v-for="item in change.evidenceBefore" :key="String(item.id)" :evidence="item" :snapshot="baseline" :paper-id="paperId" :current-source-sha="String((snapshot.source as Row | undefined)?.sha256 ?? '')" /><p v-if="!change.evidenceBefore.length">{{ t("无关联证据") }}</p></div>
          <div><h4>{{ t("修改后证据") }}</h4><FrozenEvidence v-for="item in change.evidenceAfter" :key="String(item.id)" :evidence="item" :snapshot="snapshot" :paper-id="paperId" :current-source-sha="String((snapshot.source as Row | undefined)?.sha256 ?? '')" /><p v-if="!change.evidenceAfter.length">{{ t("无关联证据") }}</p></div>
        </div>
      </article>
    </section>
    <details v-if="result.available" class="confirmation-summary" data-confirmation-summary>
      <summary>{{ t("另有 {count} 项仅确认、内容未变", {count: result.confirmations.length}) }}</summary>
      <ul><li v-for="change in result.confirmations" :key="`${change.domain}-${change.id}`">{{ t(domainLabels[change.domain] ?? change.domain) }} · {{ t(change.label) }}<span v-for="field in change.fields" :key="field.key"> · {{ valueLabel(field.key, field.before, baseline) }} → {{ valueLabel(field.key, field.after, snapshot) }}</span></li></ul>
    </details>
  </section>
</template>
<style scoped>
.comparison-explainer, .change-actors { color: var(--ink-muted); font-size: .9rem; }
.comparison-counts { display: flex; gap: .5rem 1rem; flex-wrap: wrap; padding: .8rem 0; }
.comparison-counts span { border-left: 1px solid var(--line); padding-left: 1rem; }
.remaining-issues { background: var(--amber-pale); border-left: 4px solid var(--amber-deep); padding: 1rem; margin: 1rem 0; }
.change-group { margin-top: 1.5rem; }
.change-group > h3 { border-bottom: 2px solid var(--line); padding-bottom: .65rem; }
.change-card { border: 1px solid var(--line); border-radius: 8px; padding: 1.1rem; margin: 1rem 0; }
.change-card header { display: flex; align-items: center; flex-wrap: wrap; gap: .65rem; }
.change-kind { font-size: .8rem; border-radius: 4px; background: var(--slate-pale); padding: .2rem .5rem; }
.change-kind.removed { background: var(--danger-soft); color: var(--danger); }
.change-kind.added { background: var(--teal-pale); color: var(--teal-deep); }
.change-fields-wrap { overflow-x: auto; }
.change-fields { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: .9rem; }
.change-fields th, .change-fields td { border: 1px solid var(--line); padding: .6rem .8rem; text-align: left; vertical-align: top; white-space: pre-wrap; overflow-wrap: anywhere; }
.change-fields th:first-child { width: 20%; }
.change-fields thead { background: var(--surface); }
.before-value { background: var(--surface); }.after-value { background: var(--teal-pale); }
.comparison-pair { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; margin: 1rem 0; }
.comparison-pair > div { min-width: 0; }
.comparison-pair h4 { margin: .5rem 0; }
.structure-pair img { width: 100%; max-height: 220px; object-fit: contain; display: block; }
.structure-pair code { overflow-wrap: anywhere; }
.confirmation-summary { margin-top: 1rem; padding: .8rem; background: var(--slate-pale); }
summary { cursor: pointer; }
@media(max-width: 700px) { .comparison-pair { grid-template-columns: 1fr; } .change-card { padding: .7rem; } }
</style>

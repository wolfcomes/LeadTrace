<script setup lang="ts">
import { computed, ref } from 'vue';
import { t } from '../i18n';
import type { AiReviewReport } from './aiTasks';
const props = defineProps<{ report: AiReviewReport }>();
const expanded = ref(false);
const overview = computed(() => props.report.overview);
const domainLabels: Record<string, string> = {
  compounds: 'Compound', compound: 'Compound', activities: 'Activity', activity: 'Activity',
  lineages: 'Lineage', lineage_groups: 'Lineage', edges: 'Edge', edge: 'Edge', evidence: 'Evidence',
  screenshots: '截图', structure_locators: '结构来源截图', structures: '结构',
  compound_highlights: '研究起点／论文优选', highlights: '研究起点／论文优选',
  lineage_members: 'Lineage 节点', members: 'Lineage 节点', edge_evidence_links: 'Edge 与证据关联',
  locators: '结构来源截图', links: 'Edge 与证据关联', bibliography: '文章信息', groups: 'Lineage',
};
const displayDomain = (domain: string) => t(domainLabels[domain] ?? domain);
const issueLabels: Record<string, string> = {
  COMPOUND_COVERAGE_INCOMPLETE: 'Compound 清单覆盖不足',
  STRUCTURE_IDENTITY: '结构身份需核对',
  STRUCTURE_IDENTITY_UNCERTAIN: '结构身份需核对',
  STRUCTURE_SOURCE_CROP_MISSING: '缺少结构来源截图',
  LINEAGE_DISCONNECTED: 'Lineage 存在不连通分组',
  SAR_EVIDENCE_MISSING: 'SAR 证据不足',
  UNCLASSIFIED: '未分类问题',
};
function issueLabel(code: string) {
  if (issueLabels[code]) return t(issueLabels[code]);
  const review = /^REVIEW_(INCORRECT|UNCERTAIN)_(.+)$/.exec(code);
  if (review) return `${displayDomain(review[2].toLowerCase())} · ${t(review[1] === 'INCORRECT' ? '发现错误' : '尚不确定')}`;
  return code;
}
const groups = computed(() => {
  if (overview.value) return overview.value.issue_groups;
  const counts = new Map<string, number>();
  for (const row of props.report.findings) {
    if (row.verdict === 'correct') continue;
    const key = `${row.domain} · ${row.verdict}`;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return [...counts].map(([code, count]) => ({code, count}));
});
const highlights = computed(() => (overview.value?.highlights ?? props.report.findings.filter(f => f.verdict !== 'correct').map(f => f.reason)).slice(0, 3).map(s => typeof s === 'string' ? s : s.summary).map(s => s.length > 400 ? `${s.slice(0, 400)}…` : s));
const percentage = (value: number | null) => value === null ? t('未知') : `${Number(value.toFixed(1))}%`;
const value = (n: number | null) => n === null ? '—' : n;
const proposal = computed(() => props.report.proposal);
const pretty = (input: unknown) => input === undefined || input === null ? '—' : JSON.stringify(input, null, 2);
</script>

<template>
  <section class="ai-report-overview" data-report-overview>
    <p v-if="report.repair_proposal_status" class="ai-report-context">{{ t('以下复核统计对应修改前草稿；同一次任务生成的修补方案尚未经过另一次独立复核。') }}</p>
    <p v-if="report.repair_proposal_status === 'unavailable'" class="inline-feedback is-warning" data-proposal-unavailable>{{ t('本轮未产出可接受的修补方案，复核报告已保留；未修改草稿，也未追加模型调用。') }}</p>
    <p v-if="report.repair_proposal_status === 'no_changes'" data-proposal-no-changes>{{ t('本轮未提出可据证修改；如仍有不确定项，请继续人工核对。') }}</p>
    <p v-if="report.repair_proposal_reason" class="ai-report-context">{{ report.repair_proposal_reason }}</p>
    <template v-if="overview">
      <p class="ai-report-context">{{ t(overview.basis === 'producer' ? '统计来自生成结果与生产者自检；未被标记不代表已经独立核实。' : '支持、错误与不确定来自本轮 AI 独立复核；均不代替人工科学批准。') }}</p>
      <div class="ai-report-table-scroll">
        <table class="ai-report-table">
          <caption>{{ t('内容与可信状态统计') }}</caption>
          <thead><tr><th scope="col">{{ t('类型') }}</th><th scope="col">{{ t('总数') }}</th><th scope="col">{{ t('AI复核支持') }}</th><th scope="col">{{ t('发现错误') }}</th><th scope="col">{{ t('尚不确定') }}</th><th scope="col">{{ t('未完成复核') }}</th><th scope="col">{{ t('需核对') }}</th></tr></thead>
          <tbody><tr v-for="entity in overview.entities" :key="entity.domain" :data-report-entity="entity.domain"><th scope="row">{{ displayDomain(entity.domain) }}</th><td>{{ entity.total }}</td><td>{{ value(entity.supported) }}</td><td>{{ value(entity.incorrect) }}</td><td>{{ value(entity.uncertain) }}</td><td>{{ entity.unreviewed }}</td><td>{{ entity.flagged }}</td></tr></tbody>
        </table>
      </div>
      <p class="ai-report-context">{{ t('“—”表示没有对应复核数据；需核对与其他状态可能重叠，不应相加。') }}</p>
      <dl class="ai-report-metrics">
        <div><dt>{{ t('Compound 清单覆盖率') }}</dt><dd v-if="overview.compound_coverage.known">{{ percentage(overview.compound_coverage.percent) }} <small>{{ overview.compound_coverage.covered }} / {{ overview.compound_coverage.expected }}</small></dd><dd v-else>{{ t('未知') }}</dd></div>
        <div><dt>{{ t('独立复核覆盖率') }}</dt><dd v-if="overview.audit_coverage.known">{{ percentage(overview.audit_coverage.percent) }} <small>{{ overview.audit_coverage.checked }} / {{ overview.audit_coverage.expected }}</small></dd><dd v-else>{{ t('未知') }}</dd></div>
        <div><dt>{{ t('不同截图区域') }}</dt><dd>{{ overview.unique_crop_regions }}</dd></div>
      </dl>
      <p v-if="overview.audit_scope === 'candidate_only'" class="ai-report-context">{{ t('复核范围仅包含当前候选；尚未核验完整身份清单。') }}</p>
      <p v-if="overview.screenshot_counts" class="ai-report-context">{{ t('截图记录包含 {structures} 个结构定位和 {evidence} 个证据截图；相同区域可能支持多个条目。', {structures:overview.screenshot_counts.structure_occurrences, evidence:overview.screenshot_counts.evidence_crops}) }}</p>
      <p class="ai-report-context">{{ t('清单覆盖率不等于结构准确率；复核覆盖率表示检查范围，不代表通过率。') }}</p>
    </template>
    <template v-else-if="!proposal">
      <p>{{ t('旧报告未记录完整分类统计，不推算可信数量。') }}</p>
      <p v-if="report.coverage_known === false">{{ t('完整清单缺失，覆盖率未知') }}</p>
      <p v-else>{{ t(report.report_kind === 'prefill' ? '已收录 {reviewed} / {expected} 个清单必需项' : '已检查 {reviewed} / {expected} 项', {reviewed: report.coverage.reviewed, expected: report.coverage.expected}) }}</p>
    </template>
    <section v-if="groups.length" class="ai-report-group-section"><h5>{{ t('问题类别统计') }}</h5><dl class="ai-report-groups"><div v-for="group in groups.slice(0, 12)" :key="group.code"><dt>{{ issueLabel(group.code) }}</dt><dd>{{ group.count }}</dd></div></dl><p v-if="groups.length > 12">{{ t('其他问题类别：{count}', {count: groups.length - 12}) }}</p><p v-if="report.findings_truncated">{{ t('问题类别计数仅涵盖已返回记录，完整记录保留在任务中。') }}</p></section>
    <section v-if="highlights.length" class="ai-report-group-section"><h5>{{ t('特别关注（最多 3 项）') }}</h5><ul><li v-for="(highlight, index) in highlights" :key="index">{{ highlight }}</li></ul></section>
    <section v-if="proposal" class="ai-repair-proposal" data-repair-proposal>
      <h5>{{ t('修补方案') }}</h5>
      <p>{{ t('拟修改 {count} 项；修补后自检仍有 {remaining} 项提示。', {count: proposal.total_changes, remaining: proposal.remaining_findings}) }}</p>
      <div class="ai-report-table-scroll"><table class="ai-report-table"><thead><tr><th>{{ t('类型') }}</th><th>{{ t('新增') }}</th><th>{{ t('更新') }}</th><th>{{ t('删除') }}</th></tr></thead><tbody><tr v-for="(counts, domain) in proposal.counts" :key="domain"><th>{{ displayDomain(String(domain)) }}</th><td>{{ counts.added }}</td><td>{{ counts.updated }}</td><td>{{ counts.removed }}</td></tr></tbody></table></div>
      <details data-proposal-diff><summary>{{ t('查看修改前后差异') }}</summary><article v-for="(change, index) in proposal.changes" :key="index" class="ai-repair-change"><h5>{{ displayDomain(change.domain) }} · {{ change.ref }} · {{ t(({added:'新增', updated:'更新', removed:'删除', create:'新增', update:'更新', delete:'删除'} as Record<string,string>)[change.action] ?? change.action) }}</h5><div class="ai-repair-diff"><div><strong>{{ t('修改前') }}</strong><pre>{{ pretty(change.before) }}</pre></div><div><strong>{{ t('修改后') }}</strong><pre>{{ pretty(change.after) }}</pre></div></div></article></details>
    </section>
    <details v-if="report.findings.length || report.coverage.missing.length || report.checks?.length || report.delivery_notes?.length" data-report-diagnostics @toggle="expanded = ($event.target as HTMLDetailsElement).open">
      <summary>{{ t('展开原始诊断记录（按需查看）') }}</summary>
      <template v-if="expanded">
        <p v-if="report.coverage.missing.length">{{ t('未覆盖条目') }} · {{ report.coverage.missing.length }}</p>
        <ul><li v-for="missing in report.coverage.missing" :key="`${missing.domain}:${missing.ref}`">{{ missing.domain }} · {{ missing.ref }}</li></ul>
        <ul><li v-for="(finding, index) in report.findings" :key="index"><strong>{{ finding.domain }} · {{ finding.ref }} · {{ finding.verdict }}</strong><p>{{ finding.reason }}</p><small>{{ finding.source_locator }}</small></li></ul>
        <ul v-if="report.checks?.length"><li v-for="check in report.checks" :key="check.check_id"><strong>{{ check.check_id }} · {{ check.status }}</strong><p>{{ check.details }}</p></li></ul>
        <section v-if="report.delivery_notes?.length"><h5>{{ t('导入处理记录') }}</h5><div v-for="note in report.delivery_notes" :key="note.locator_refs.join(',')"><strong>{{ note.compound_ref }} · {{ t('第 {page} 页', {page:note.page_number}) }}</strong><p>{{ t('重复的同位置截图已合并，原定位引用和来源说明均已保留。') }}</p><small>{{ note.locator_refs.join(', ') }}</small><details v-if="note.annotations?.length"><summary>{{ t('原始来源说明') }}</summary><div v-for="annotation in note.annotations" :key="annotation.ref"><strong>{{ annotation.ref }} · {{ annotation.label }}</strong><p class="ai-report-annotation">{{ annotation.source_context }}</p></div></details></div></section>
      </template>
    </details>
  </section>
</template>

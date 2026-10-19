import { t } from "../i18n";
import { statusLabel } from "../i18n/status";
import type { RecordKind } from "./recordComparison";
export const changeLabels: Record<RecordKind | "evidence", string> = {
  added: "新增",
  removed: "删除",
  modified: "已修改",
  unchanged: "内容未变",
  unknown: "比较起点不可用",
  evidence: "证据更新",
};
export const domainLabels: Record<string, string> = {
  activity_tables: "活性对比",
  paper: "文章信息",
  source: "原文来源",
  sections: "区段状态",
  compounds: "化合物",
  structures: "结构",
  structure_source_images: "结构证据",
  lineages: "Lineage",
  lineage_members: "Lineage 成员",
  lineage_edges: "关系",
  evidence: "证据",
  edge_evidence_links: "证据关联",
  activities: "活性",
  compound_highlights: "关键化合物",
};
export const fieldLabels: Record<string, string> = {
  compound_label: "化合物编号",
  display_name: "名称",
  description: "说明",
  sort_order: "排序",
  status: "状态",
  review_status: "核对状态",
  review_hint: "核对提示",
  smiles: "SMILES",
  canonical_smiles: "Canonical SMILES",
  molfile: "Molfile",
  inchi: "InChI",
  inchikey: "InChIKey",
  lineage_label: "Lineage 名称",
  lineage_type: "Lineage 类型",
  relation_type: "关系类型",
  modification_summary: "结构变化说明",
  role: "作用",
  assay_name: "实验名称",
  metric: "指标",
  operator: "比较符号",
  value: "数值",
  unit: "单位",
  context: "实验条件",
  kind: "证据类型",
  page_number: "页码",
  quoted_text: "原文摘录",
  caption: "标题",
  reviewer_note: "核对说明",
  source_context: "原文位置",
  label: "标签",
  state: "区段状态",
  note: "说明",
  section_key: "区段",
  title: "文章标题",
  journal: "期刊",
  doi: "DOI",
  publication_year: "年份",
  volume: "卷",
  issue: "期",
  sha256: "原文指纹",
  page_count: "页数",
  source_key: "原文路径",
  source_root_key: "原文目录",
  paper_key: "文章编号",
  reason: "原因",
  highlight_type: "标记类型",
  scope: "适用范围",
  rationale: "选择依据",
  pmid: "PubMed ID", pmcid: "PubMed Central ID", identifiers_source: "标识来源",
  abstract_status: "摘要检查状态", abstract_note: "摘要检查说明", research_profile: "研究主题信息",
  abstract: "摘要",
  abstract_source: "摘要来源",
  pdb_references: "PDB 结构引用",
};
const stateLabels: Record<string, string> = {
  not_checked:"尚未检查",extracted:"已提取",not_found:"已检查，未找到",
  draft: "待确认",
  ai_draft: "待确认",
  reviewer_confirmed: "已确认",
  unresolved: "未解决",
  not_reported: "原文未报告",
  completed: "已完成",
  pending: "待确认",
  needs_revision: "待修改",
  needs_review: "待核对",
  root: "起点",
  intermediate: "中间节点",
  terminal: "终点",
  supports: "支持",
  contradicts: "反驳",
  context: "上下文",
  study_start: "研究起点",
  optimization_start: "枢纽分子",
  paper_selected: "论文优选",
  unspecified: "待分类",
  sar: "SAR / 结构优化",
  synthesis: "化学合成",
};
export function reviewState(value: unknown): string {
  return stateLabels[String(value)]
    ? t(stateLabels[String(value)])
    : statusLabel(value);
}
export function textValue(value: unknown): string {
  if (value == null || value === "") return "—";
  if (Array.isArray(value)) return value.map(textValue).join(" · ");
  if (typeof value === "object")
    return Object.entries(value)
      .map(([k, v]) => `${t(fieldLabels[k] ?? k)}: ${textValue(v)}`)
      .join("; ");
  return String(value);
}
export function assetUrl(id: unknown): string {
  return `/api/v1/assets/${encodeURIComponent(String(id))}/content`;
}

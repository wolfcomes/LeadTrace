import type { ChangeEvent } from "../v2/types";

export type Row = Record<string, unknown>;
export interface Snapshot {
  paper: Row; source?: Row; sections: Row[]; compounds: Row[]; structures: Row[];
  structure_source_images: Row[]; lineages: Row[]; lineage_members: Row[];
  lineage_edges: Row[]; evidence: Row[]; edge_evidence_links: Row[]; activities: Row[];
  compound_highlights?: Row[];
  [key: string]: unknown;
}
export interface Comparison {
  kind: "previous_submission" | "reviewer_start" | "unavailable";
  baseline_submission_number: number | null;
  baseline_snapshot: Record<string, unknown> | null;
  events: ChangeEvent[]; warnings: string[];
}
export interface FieldChange { key: string; before: unknown; after: unknown }
export interface ScientificChange {
  id: string; domain: string; label: string; group: string; kind: "added" | "removed" | "modified";
  before: Row | null; after: Row | null; fields: FieldChange[]; actors: string[];
  issueResolution: boolean; evidenceBefore: Row[]; evidenceAfter: Row[];
}
const domains = ["paper", "source", "sections", "compounds", "structures", "structure_source_images", "lineages", "lineage_members", "lineage_edges", "evidence", "edge_evidence_links", "activities", "compound_highlights", "activity_tables"];
const eventDomains: Record<string, string> = {
  compound: "compounds", structure: "structures", structure_source_image: "structure_source_images",
  lineage: "lineages", lineage_member: "lineage_members", lineage_edge: "lineage_edges",
  evidence: "evidence", edge_evidence_link: "edge_evidence_links", activity: "activities",
  activity_table: "activity_tables", compound_highlight: "compound_highlights", paper_section_review: "sections", section: "sections", paper: "paper",
};
// Derived rendering assets and operational metadata are not scientific edits.
const ignored = new Set(["id", "paper_id", "workspace_id", "created_at", "updated_at", "created_by_kind", "created_by_id", "version", "depiction_asset_id", "crop_asset_id", "crop_status", "input_method", "catalog_state"]);
export function rows(snapshot: Record<string, unknown>, domain: string): Row[] {
  const value = snapshot[domain];
  if (domain === "paper" || domain === "source") return value && typeof value === "object" ? [value as Row] : [];
  return Array.isArray(value) ? value.filter(row => row && typeof row === "object").map(row => domain === "lineages" ? {lineage_type: "unspecified", ...row} : row) : [];
}
function identity(row: Row, domain: string): string { return String(row.id ?? row.section_key ?? domain); }
function stable(value: unknown): string {
  if (value === undefined || value === null || value === "") return "null";
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (typeof value === "object") return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => `${k}:${stable(v)}`).join(",")}}`;
  return JSON.stringify(value);
}
// Canonical coefficient/exponent pairs avoid rounding distinct scientific values
// through JavaScript Number, and avoid allocating enormous exponent expansions.
function fieldValue(key: string, value: unknown): string {
  if (["value", "x0", "y0", "x1", "y1"].includes(key) && (typeof value === "string" || typeof value === "number")) {
    const match = String(value).match(/^(-?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/);
    if (match && (match[2] || match[3])) {
      let digits = `${match[2]}${match[3] ?? ""}`.replace(/^0+/, "");
      if (!digits) return "0";
      const trailing = digits.length - digits.replace(/0+$/, "").length;
      digits = digits.slice(0, digits.length - trailing);
      const exponent = BigInt(match[4] ?? "0") - BigInt((match[3] ?? "").length) + BigInt(trailing);
      return `${match[1]}${digits}e${exponent}`;
    }
  }
  return stable(value);
}
function find(snapshot: Record<string, unknown>, domain: string, id: unknown): Row | undefined { return rows(snapshot, domain).find(row => row.id === id); }
export function compoundLabel(snapshot: Record<string, unknown>, id: unknown): string { return String(find(snapshot, "compounds", id)?.compound_label ?? id ?? "—"); }
export function edgeLabel(snapshot: Record<string, unknown>, id: unknown): string {
  const edge = find(snapshot, "lineage_edges", id);
  return edge ? `${compoundLabel(snapshot, edge.parent_compound_id)} → ${compoundLabel(snapshot, edge.child_compound_id)}` : String(id ?? "—");
}
export function recordLabel(snapshot: Record<string, unknown>, domain: string, row: Row): string {
  if (domain === "paper") return "文章信息";
  if (domain === "source") return "原文来源";
  if (domain === "sections") return String(row.section_key);
  if (domain === "compounds") return String(row.compound_label ?? row.id);
  if (domain === "activity_tables") return String(row.name ?? row.source_label ?? row.id);
  if (domain === "lineages") return String(row.lineage_label ?? row.id);
  if (domain === "lineage_edges") return `${compoundLabel(snapshot, row.parent_compound_id)} → ${compoundLabel(snapshot, row.child_compound_id)}`;
  if (domain === "edge_evidence_links") return edgeLabel(snapshot, row.edge_id);
  if (domain === "evidence") return String(row.caption || `Evidence · ${row.page_number}`);
  if (row.compound_id) return compoundLabel(snapshot, row.compound_id);
  return String(row.id ?? "—");
}
function evidenceFor(snapshot: Record<string, unknown>, domain: string, row: Row | null): Row[] {
  if (!row) return [];
  if (domain === "evidence" || domain === "structure_source_images") return [row];
  let ids: unknown[] = [];
  if (row.evidence_id) ids.push(row.evidence_id);
  if (domain === "lineage_edges") ids = rows(snapshot, "edge_evidence_links").filter(link => link.edge_id === row.id).map(link => link.evidence_id);
  if (domain === "structures" || domain === "compounds") return rows(snapshot, "structure_source_images").filter(image => image.compound_id === (domain === "compounds" ? row.id : row.compound_id));
  return rows(snapshot, "evidence").filter(evidence => ids.includes(evidence.id));
}
export function evidenceUsage(snapshot: Record<string, unknown>, evidence: Row): string[] {
  if (evidence.compound_id) return [compoundLabel(snapshot, evidence.compound_id)];
  return [...new Set([
    ...rows(snapshot, "activities").filter(row => row.evidence_id === evidence.id).map(row => `${compoundLabel(snapshot, row.compound_id)} · ${row.assay_name} · ${row.metric}`),
    ...rows(snapshot, "edge_evidence_links").filter(row => row.evidence_id === evidence.id).map(row => `${edgeLabel(snapshot, row.edge_id)} · ${row.role}`),
    ...rows(snapshot, "compound_highlights").filter(row => row.evidence_id === evidence.id).map(row => compoundLabel(snapshot, row.compound_id)),
  ])];
}
const problemStates = new Set(["unresolved", "needs_revision", "not_reported", "needs_review", "rejected"]);
function sameChemicalIdentity(before: Row | null, after: Row | null): boolean {
  if (!before?.canonical_smiles || before.canonical_smiles !== after?.canonical_smiles) return false;
  return ["inchikey", "inchi"].every(key => stable(before[key]) === stable(after[key]));
}
function ordinaryConfirmation(field: FieldChange): boolean {
  return (["status", "review_status"].includes(field.key) && field.after === "reviewer_confirmed" && !problemStates.has(String(field.before)))
    || (field.key === "state" && field.after === "completed" && !problemStates.has(String(field.before)));
}
export function buildComparison(current: Record<string, unknown>, comparison?: Comparison) {
  const before = comparison?.baseline_snapshot;
  const available = Boolean(before && comparison?.kind !== "unavailable");
  const warnings = [...(comparison?.warnings ?? [])];
  if (!available) warnings.unshift("比较起点不可用，无法可靠判断本次修改；请检查完整提交内容及操作历史。");
  const changes: ScientificChange[] = [], confirmations: ScientificChange[] = [];
  const issues: { id: string; label: string; domain: string; detail: string }[] = [];
  for (const domain of domains) {
    for (const row of rows(current, domain)) {
      const state = row.status ?? row.review_status ?? row.state;
      if (state === "unresolved" || state === "needs_revision" || state === "needs_review" || row.review_hint) {
        issues.push({ id: identity(row, domain), label: recordLabel(current, domain, row), domain, detail: String(row.review_hint || state) });
      }
    }
    if (!available || !before) continue;
    const oldRows = new Map(rows(before, domain).map(row => [identity(row, domain), row]));
    const newRows = new Map(rows(current, domain).map(row => [identity(row, domain), row]));
    for (const id of new Set([...oldRows.keys(), ...newRows.keys()])) {
      const old = oldRows.get(id) ?? null, next = newRows.get(id) ?? null;
      const fields = [...new Set([...Object.keys(old ?? {}), ...Object.keys(next ?? {})])]
        .filter(key => !ignored.has(key) && !(domain === "structures" && ["smiles", "molfile"].includes(key) && sameChemicalIdentity(old, next)) && fieldValue(key, old?.[key]) !== fieldValue(key, next?.[key]))
        .map(key => ({key, before: old?.[key], after: next?.[key]}));
      if (old && next && !fields.length) continue;
      const row = next ?? old!, source = next ? current : before;
      const label = recordLabel(source, domain, row);
      const relatedEdge = domain === "edge_evidence_links" ? find(source, "lineage_edges", row.edge_id) : undefined;
      const lineageId = row.lineage_id ?? relatedEdge?.lineage_id;
      const group = row.compound_id ? compoundLabel(source, row.compound_id)
        : domain === "compounds" ? label
        : lineageId ? String(find(source, "lineages", lineageId)?.lineage_label ?? label)
        : domain === "lineages" ? label : domain === "evidence" ? "证据" : "文章与其他修改";
      const actors = [...new Set((comparison?.events ?? []).filter(event => (eventDomains[event.entity_type] ?? event.entity_type) === domain && (domain === "sections" ? (event.after_value?.section_key ?? event.before_value?.section_key) === id : event.entity_id === id)).map(event => event.actor_kind))];
      const change: ScientificChange = {
        id, domain, label, group, kind: !old ? "added" : !next ? "removed" : "modified", before: old, after: next, fields, actors,
        issueResolution: fields.some(field => (field.key === "review_hint" && Boolean(field.before) && !field.after) || (["status", "review_status", "state"].includes(field.key) && problemStates.has(String(field.before)) && !problemStates.has(String(field.after)))),
        evidenceBefore: evidenceFor(before, domain, old), evidenceAfter: evidenceFor(current, domain, next),
      };
      if (old && next && fields.every(ordinaryConfirmation)) confirmations.push(change);
      else changes.push(change);
    }
  }
  const groups = [...new Set(changes.map(change => change.group))].map(label => ({label, changes: changes.filter(change => change.group === label)}));
  return {available, warnings, changes, confirmations, groups, issues};
}

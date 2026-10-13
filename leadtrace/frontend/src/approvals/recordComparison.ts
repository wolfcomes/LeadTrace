import {
  buildComparison,
  rows,
  type Comparison,
  type Row,
  type ScientificChange,
} from "./comparison";
export type FrozenSnapshot = Record<string, unknown>;
export type RecordKind =
  "added" | "removed" | "modified" | "unchanged" | "unknown";
export interface CompoundRecord {
  compound: Row;
  structures: Row[];
  images: Row[];
  activities: Row[];
  highlights: Row[];
  evidence: Row[];
}
export interface LineageRecord {
  lineage: Row;
  members: Row[];
  edges: Row[];
  links: Row[];
  evidence: Row[];
  compounds: CompoundRecord[];
}
export interface PairedRecord<T> {
  id: string;
  label: string;
  before: T | null;
  after: T | null;
  changed: boolean;
  kind: RecordKind;
  changes: ScientificChange[];
}
export function compoundRecord(
  snapshot: FrozenSnapshot,
  id: string,
): CompoundRecord | null {
  const compound = rows(snapshot, "compounds").find((x) => x.id === id);
  if (!compound) return null;
  const related = (domain: string) =>
    rows(snapshot, domain).filter((x) => x.compound_id === id);
  const activities = related("activities"),
    highlights = related("compound_highlights");
  const evidenceIds = new Set(
    [...activities, ...highlights].map((x) => x.evidence_id),
  );
  return {
    compound,
    structures: related("structures"),
    images: related("structure_source_images"),
    activities,
    highlights,
    evidence: rows(snapshot, "evidence").filter((x) => evidenceIds.has(x.id)),
  };
}
export function lineageRecord(
  snapshot: FrozenSnapshot,
  id: string,
): LineageRecord | null {
  const lineage = rows(snapshot, "lineages").find((x) => x.id === id);
  if (!lineage) return null;
  const members = rows(snapshot, "lineage_members").filter(
    (x) => x.lineage_id === id,
  );
  const edges = rows(snapshot, "lineage_edges").filter(
    (x) => x.lineage_id === id,
  );
  const links = rows(snapshot, "edge_evidence_links").filter((x) =>
    edges.some((e) => e.id === x.edge_id),
  );
  const ids = new Set([
    ...members.map((x) => x.compound_id),
    ...edges.flatMap((x) => [x.parent_compound_id, x.child_compound_id]),
  ]);
  return {
    lineage,
    members,
    edges,
    links,
    evidence: rows(snapshot, "evidence").filter((x) =>
      links.some((l) => l.evidence_id === x.id),
    ),
    compounds: [...ids]
      .map((x) => compoundRecord(snapshot, String(x)))
      .filter((x): x is CompoundRecord => Boolean(x)),
  };
}
function containsCompoundChange(
  record: CompoundRecord | null,
  change: ScientificChange,
): boolean {
  if (!record) return false;
  if (change.domain === "compounds") return record.compound.id === change.id;
  const domains: Record<string, Row[]> = {
    structures: record.structures,
    structure_source_images: record.images,
    activities: record.activities,
    compound_highlights: record.highlights,
    evidence: record.evidence,
  };
  return (domains[change.domain] ?? []).some((x) => x.id === change.id);
}
function containsLineageChange(
  record: LineageRecord | null,
  change: ScientificChange,
): boolean {
  if (!record) return false;
  if (change.domain === "lineages") return record.lineage.id === change.id;
  const domains: Record<string, Row[]> = {
    lineage_members: record.members,
    lineage_edges: record.edges,
    edge_evidence_links: record.links,
    evidence: record.evidence,
  };
  return (
    (domains[change.domain] ?? []).some((x) => x.id === change.id) ||
    record.compounds.some((x) => containsCompoundChange(x, change))
  );
}
export function buildRecordComparison(
  current: FrozenSnapshot,
  comparison?: Comparison,
) {
  const result = buildComparison(current, comparison),
    baseline = comparison?.baseline_snapshot ?? {};
  function records<T>(
    domain: string,
    build: (s: FrozenSnapshot, id: string) => T | null,
    includes: (r: T | null, c: ScientificChange) => boolean,
  ): PairedRecord<T>[] {
    const oldRows = result.available ? rows(baseline, domain) : [],
      newRows = rows(current, domain);
    const all = [
      ...new Map(
        [...oldRows, ...newRows].map((x) => [String(x.id), x]),
      ).values(),
    ];
    return all
      .sort(
        (a, b) =>
          Number(a.sort_order ?? 0) - Number(b.sort_order ?? 0) ||
          String(a.id).localeCompare(String(b.id)),
      )
      .map((row) => {
        const id = String(row.id),
          before = result.available ? build(baseline, id) : null,
          after = build(current, id);
        const changes = result.changes.filter(
          (c) => includes(before, c) || includes(after, c),
        );
        return {
          id,
          label: String(row.compound_label ?? row.lineage_label ?? id),
          before,
          after,
          changes,
          changed: changes.length > 0,
          kind: !result.available
            ? "unknown"
            : !before
              ? "added"
              : !after
                ? "removed"
                : changes.length
                  ? "modified"
                  : "unchanged",
        };
      });
  }
  const compounds = records(
      "compounds",
      compoundRecord,
      containsCompoundChange,
    ),
    lineages = records("lineages", lineageRecord, containsLineageChange);
  const covered = new Set(
    [...compounds, ...lineages].flatMap((r) => r.changes),
  );
  const changes = result.changes.filter((c) => !covered.has(c));
  const article: PairedRecord<FrozenSnapshot> = {
    id: "article",
    label: "文章信息",
    before: result.available ? baseline : null,
    after: current,
    changed: changes.length > 0,
    changes,
    kind: !result.available
      ? "unknown"
      : changes.length
        ? "modified"
        : "unchanged",
  };
  return { ...result, compounds, lineages, article };
}
export interface GraphNode {
  id: string;
  label: string;
  depiction?: string;
  position: { x: number; y: number };
  change: RecordKind;
  role: string;
}
export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  change: RecordKind | "evidence";
}
export interface FrozenGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}
export function lineageGraphPair(record: PairedRecord<LineageRecord>): {
  before: FrozenGraph;
  after: FrozenGraph;
} {
  const nodeIds = (r: LineageRecord | null) => [
    ...new Set([
      ...(r?.members.map((x) => String(x.compound_id)) ?? []),
      ...(r?.edges.flatMap((x) => [
        String(x.parent_compound_id),
        String(x.child_compound_id),
      ]) ?? []),
    ]),
  ];
  const oldIds = nodeIds(record.before),
    newIds = nodeIds(record.after),
    ids = [...new Set([...oldIds, ...newIds])].sort();
  const columns = Math.max(1, Math.ceil(Math.sqrt(ids.length)));
  const positions = new Map(
    ids.map((id, i) => [
      id,
      { x: (i % columns) * 170 + 80, y: Math.floor(i / columns) * 120 + 60 },
    ]),
  );
  function graph(side: "before" | "after"): FrozenGraph {
    const own = record[side],
      other = record[side === "before" ? "after" : "before"];
    const oppositeIds = side === "before" ? newIds : oldIds;
    return {
      nodes: nodeIds(own).map((id) => {
        const compound = own?.compounds.find((x) => x.compound.id === id),
          member = own?.members.find((x) => x.compound_id === id);
        const changed = record.changes.some(
          (c) =>
            containsCompoundChange(compound ?? null, c) ||
            (c.domain === "lineage_members" &&
              (c.before?.compound_id === id || c.after?.compound_id === id)),
        );
        return {
          id,
          label: String(compound?.compound.compound_label ?? id),
          depiction: compound?.structures[0]?.depiction_asset_id
            ? String(compound.structures[0].depiction_asset_id)
            : undefined,
          position: positions.get(id)!,
          role: String(member?.role ?? ""),
          change:
            record.kind === "unknown"
              ? "unknown"
              : !oppositeIds.includes(id)
                ? side === "before"
                  ? "removed"
                  : "added"
                : changed
                  ? "modified"
                  : "unchanged",
        };
      }),
      edges: (own?.edges ?? []).map((edge) => {
        const exists = other?.edges.some((x) => x.id === edge.id),
          direct = record.changes.some(
            (c) => c.domain === "lineage_edges" && c.id === edge.id,
          );
        const links = [...(own?.links ?? []), ...(other?.links ?? [])].filter(
          (x) => x.edge_id === edge.id,
        );
        const evidenceChanged = record.changes.some(
          (c) =>
            (c.domain === "edge_evidence_links" &&
              links.some((l) => l.id === c.id)) ||
            (c.domain === "evidence" &&
              links.some((l) => l.evidence_id === c.id)),
        );
        return {
          id: String(edge.id),
          source: String(edge.parent_compound_id),
          target: String(edge.child_compound_id),
          label: String(edge.relation_type ?? ""),
          change:
            record.kind === "unknown"
              ? "unknown"
              : !exists
                ? side === "before"
                  ? "removed"
                  : "added"
                : direct
                  ? "modified"
                  : evidenceChanged
                    ? "evidence"
                    : "unchanged",
        };
      }),
    };
  }
  return { before: graph("before"), after: graph("after") };
}

export function issueTarget(
  snapshot: FrozenSnapshot,
  issue: { id: string; domain: string },
): {
  tab: "article" | "compounds" | "lineages";
  recordId: string;
  selection: string;
} {
  const row = rows(snapshot, issue.domain).find(
    (x) => String(x.id ?? x.section_key) === issue.id,
  );
  const article = {
    tab: "article" as const,
    recordId: "article",
    selection: "",
  };
  if (!row) return article;
  if (issue.domain === "lineages")
    return { tab: "lineages", recordId: issue.id, selection: "" };
  if (issue.domain === "lineage_members")
    return {
      tab: "lineages",
      recordId: String(row.lineage_id),
      selection: String(row.compound_id),
    };
  if (issue.domain === "lineage_edges")
    return {
      tab: "lineages",
      recordId: String(row.lineage_id),
      selection: issue.id,
    };
  if (issue.domain === "edge_evidence_links" || issue.domain === "evidence") {
    const link =
      issue.domain === "edge_evidence_links"
        ? row
        : rows(snapshot, "edge_evidence_links").find(
            (x) => x.evidence_id === row.id,
          );
    const edge = rows(snapshot, "lineage_edges").find(
      (x) => x.id === link?.edge_id,
    );
    if (edge)
      return {
        tab: "lineages",
        recordId: String(edge.lineage_id),
        selection: String(edge.id),
      };
    const owner =
      rows(snapshot, "activities").find((x) => x.evidence_id === row.id) ??
      rows(snapshot, "compound_highlights").find(
        (x) => x.evidence_id === row.id,
      );
    if (owner)
      return {
        tab: "compounds",
        recordId: String(owner.compound_id),
        selection: "",
      };
  }
  if (issue.domain === "compounds" || row.compound_id)
    return {
      tab: "compounds",
      recordId: String(issue.domain === "compounds" ? row.id : row.compound_id),
      selection: "",
    };
  return article;
}

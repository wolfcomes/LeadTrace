import { describe, expect, it } from "vitest";
import {
  buildRecordComparison,
  lineageGraphPair,
} from "../src/approvals/recordComparison";
import {
  frozenSnapshot,
  publicationIds as ids,
} from "./paper-publication-v2-fixtures";
import type { Snapshot } from "../src/approvals/comparison";
const snapshot = (): Snapshot => structuredClone(frozenSnapshot);
function project(before: Snapshot, after: Snapshot) {
  return buildRecordComparison(after, {
    kind: "reviewer_start",
    baseline_submission_number: null,
    baseline_snapshot: before,
    events: [],
    warnings: [],
  });
}
describe("frozen approval records", () => {
  it("propagates evidence changes to complete compound and lineage records with unchanged context", () => {
    const before = snapshot(),
      after = snapshot();
    after.evidence[0].quoted_text = "Corrected evidence";
    const result = project(before, after);
    expect(result.compounds.filter((x) => x.changed).map((x) => x.id)).toEqual([
      ids.compoundB,
    ]);
    expect(result.lineages.filter((x) => x.changed).map((x) => x.id)).toEqual([
      ids.lineage,
    ]);
    expect(result.compounds[1].after?.activities[0].assay_name).toBe(
      "Cell potency",
    );
    expect(result.lineages[0].after?.members).toHaveLength(2);
    expect(
      result.lineages[0].changes.some((x) => x.domain === "evidence"),
    ).toBe(true);
  });
  it("keeps member structure and activity changes out of lineage approval", () => {
    const before = snapshot(),
      after = snapshot();
    after.structures[0].canonical_smiles = "CCCO";
    after.activities[0].value = "125";
    const result = project(before, after),
      pair = lineageGraphPair(result.lineages[0]);
    expect(result.lineages[0].changed).toBe(false);
    expect(pair.before.nodes.find((x) => x.id === ids.compoundA)?.change).toBe(
      "unchanged",
    );
    expect(pair.after.edges[0].change).toBe("unchanged");
    expect(pair.before.nodes.map((x) => x.position)).toEqual(
      pair.after.nodes.map((x) => x.position),
    );
  });
  it("keeps confirmations out of changed records and numerical/chemical equivalence", () => {
    const before = snapshot(),
      after = snapshot();
    before.structures[0].status = "draft";
    after.activities[0].value = "12.500";
    after.structures[0].smiles = "OCC";
    const result = project(before, after);
    expect(result.compounds.every((x) => !x.changed)).toBe(true);
    expect(result.lineages.every((x) => !x.changed)).toBe(true);
    expect(result.confirmations).toHaveLength(1);
  });
  it("retains old-side associations when a relation, compound or evidence association is removed", () => {
    const before = snapshot(),
      after = snapshot();
    after.compounds.pop();
    after.activities = [];
    after.structures.pop();
    after.lineage_members.pop();
    after.lineage_edges = [];
    after.edge_evidence_links = [];
    const result = project(before, after),
      pair = lineageGraphPair(result.lineages[0]);
    expect(result.compounds[1].before?.compound.compound_label).toBe(
      "Compound 18",
    );
    expect(result.compounds[1].after).toBeNull();
    expect(pair.before.edges[0].change).toBe("removed");
    expect(pair.after.edges).toHaveLength(0);
    expect(pair.before.nodes[0].position).toEqual(pair.after.nodes[0].position);
  });
  it("includes standalone evidence in article records and handles absent baseline honestly", () => {
    const before = snapshot(),
      after = snapshot();
    after.evidence.push({
      ...after.evidence[0],
      id: "standalone",
      caption: "Standalone",
    });
    expect(project(before, after).article.changed).toBe(true);
    const result = buildRecordComparison(after);
    expect(result.available).toBe(false);
    expect(result.compounds).toHaveLength(2);
    expect(result.compounds[0].kind).toBe("unknown");
    expect(result.compounds[0].before).toBeNull();
  });
});

describe("whole lineage change identity", () => {
  it("distinguishes evidence-only updates from rewired relationships with stable IDs", () => {
    const before = snapshot(),
      after = snapshot();
    after.evidence[0].quoted_text = "Updated source quotation";
    let pair = lineageGraphPair(project(before, after).lineages[0]);
    expect(pair.before.edges[0].change).toBe("evidence");
    expect(pair.after.edges[0].change).toBe("evidence");
    after.lineage_edges[0].parent_compound_id = ids.compoundB;
    after.lineage_edges[0].child_compound_id = ids.compoundA;
    pair = lineageGraphPair(project(before, after).lineages[0]);
    expect(pair.before.edges[0].source).toBe(ids.compoundA);
    expect(pair.after.edges[0].source).toBe(ids.compoundB);
    expect(pair.after.edges[0].change).toBe("modified");
  });
});

describe("lineage topology and edge scope", () => {
  it("does not propagate activity-only evidence but keeps evidence used by an edge", () => {
    const before = snapshot(),
      after = snapshot();
    before.edge_evidence_links = [];
    after.edge_evidence_links = [];
    after.evidence[0].quoted_text = "Activity evidence update";
    expect(project(before, after).lineages[0].changed).toBe(false);
    expect(project(before, after).compounds[1].changed).toBe(true);
    before.edge_evidence_links = structuredClone(
      frozenSnapshot.edge_evidence_links,
    );
    after.edge_evidence_links = structuredClone(
      frozenSnapshot.edge_evidence_links,
    );
    expect(
      lineageGraphPair(project(before, after).lineages[0]).after.edges[0]
        .change,
    ).toBe("evidence");
  });
  it("ignores compound identity and member role-only edits without routing them into article changes", () => {
    const before = snapshot(),
      after = snapshot();
    after.compounds[1].description = "Compound-only correction";
    after.lineage_members[1].role = "root";
    const result = project(before, after);
    expect(result.lineages[0].changed).toBe(false);
    expect(result.article.changed).toBe(false);
    expect(result.changes.map(c => c.domain)).toEqual(['compounds']);
    expect(
      lineageGraphPair(result.lineages[0]).after.nodes.every(
        (n) => n.change === "unchanged",
      ),
    ).toBe(true);
  });
  it("compares node membership by compound identity, including replacement and recreated member rows", () => {
    const before = snapshot(),
      after = snapshot();
    after.lineage_members[1].id = "recreated-member";
    expect(project(before, after).lineages[0].changed).toBe(false);
    after.lineage_members[1].compound_id = "new-node";
    after.lineage_edges = [];
    after.edge_evidence_links = [];
    const result = project(before, after),
      pair = lineageGraphPair(result.lineages[0]);
    expect(result.lineages[0].changed).toBe(true);
    expect(pair.before.nodes.find((n) => n.id === ids.compoundB)?.change).toBe(
      "removed",
    );
    expect(pair.after.nodes.find((n) => n.id === "new-node")?.change).toBe(
      "added",
    );
  });
});

describe("edge-local change markers", () => {
  function multipleEdges() {
    const before = snapshot();
    before.lineage_edges = Array.from({ length: 3 }, (_, i) => ({
      ...before.lineage_edges[0], id: `edge-${i}`,
    }));
    before.edge_evidence_links = before.lineage_edges.map((edge, i) => ({
      ...before.edge_evidence_links[0], id: `link-${i}`, edge_id: edge.id,
      evidence_id: i < 2 ? ids.evidence : 'unrelated-evidence',
    }));
    before.evidence.push({ ...before.evidence[0], id: 'unrelated-evidence' });
    return before;
  }
  it('marks only the edited edge even with identical types, endpoints and shared evidence', () => {
    const before = multipleEdges(), after = structuredClone(before);
    after.lineage_edges[1].modification_summary = 'Corrected relationship';
    const pair = lineageGraphPair(project(before, after).lineages[0]);
    for (const side of ['before', 'after'] as const) {
      expect(pair[side].edges.map(e => e.change)).toEqual(['unchanged', 'modified', 'unchanged']);
    }
  });
  it('limits evidence link edits to their own edge and shared evidence edits to actual consumers', () => {
    const before = multipleEdges(), after = structuredClone(before);
    after.edge_evidence_links[0].role = 'contradicts';
    let pair = lineageGraphPair(project(before, after).lineages[0]);
    expect(pair.after.edges.map(e => e.change)).toEqual(['evidence', 'unchanged', 'unchanged']);
    after.edge_evidence_links = structuredClone(before.edge_evidence_links);
    after.evidence[0].caption = 'Updated shared evidence';
    pair = lineageGraphPair(project(before, after).lineages[0]);
    expect(pair.after.edges.map(e => e.change)).toEqual(['evidence', 'evidence', 'unchanged']);
  });
});

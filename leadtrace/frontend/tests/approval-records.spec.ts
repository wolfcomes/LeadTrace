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
  it("propagates member structure and activity changes without pretending topology changed", () => {
    const before = snapshot(),
      after = snapshot();
    after.structures[0].canonical_smiles = "CCCO";
    after.activities[0].value = "125";
    const result = project(before, after),
      pair = lineageGraphPair(result.lineages[0]);
    expect(result.lineages[0].changed).toBe(true);
    expect(pair.before.nodes.find((x) => x.id === ids.compoundA)?.change).toBe(
      "modified",
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

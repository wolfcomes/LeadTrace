import { describe, expect, it } from "vitest";
import type { ChangeEvent } from "../src/v2/types";
import { buildComparison, type Snapshot } from "../src/approvals/comparison";
import { frozenSnapshot, reviewerEvent, publicationIds } from "./paper-publication-v2-fixtures";
const snapshot = (): Snapshot => structuredClone(frozenSnapshot);
function compare(before: Snapshot, after: Snapshot, events: ChangeEvent[] = [reviewerEvent]) {
  return buildComparison(after, { kind: "reviewer_start", baseline_submission_number: null, baseline_snapshot: before, events, warnings: [] });
}
describe("approval net scientific comparison", () => {
  it("collapses ordinary confirmation while retaining issue resolution and cleared hints", () => {
    const before = snapshot(), after = snapshot();
    before.structures[0].status = "draft";
    before.structures[1].status = "unresolved";
    before.compounds[0].review_hint = "Check stereochemistry";
    after.compounds[0].review_hint = null;
    const result = compare(before, after);
    expect(result.confirmations).toHaveLength(1);
    expect(result.changes.map(row => row.domain)).toEqual(["compounds", "structures"]);
    expect(result.changes.every(row => row.issueResolution)).toBe(true);
  });
  it("compares final values once, omits reverted changes and asset regeneration, and keeps all actors", () => {
    const before = snapshot(), after = snapshot();
    after.structures[0].depiction_asset_id = "regenerated";
    after.activities[0].value = "120";
    const events = [reviewerEvent, {...reviewerEvent, entity_type: "activity", entity_id: publicationIds.activity, actor_kind: "admin" as const}];
    const result = compare(before, after, events);
    expect(result.changes).toHaveLength(1);
    expect(result.changes[0].fields.map(row => row.key)).toEqual(["value"]);
    expect(result.changes[0].actors).toEqual(["admin"]);
    expect(result.groups[0].label).toContain("Compound 18");
  });
  it("shows evidence deletion and rebinding with old and new context", () => {
    const before = snapshot(), after = snapshot();
    after.evidence = [];
    after.activities[0].evidence_id = null;
    after.edge_evidence_links = [];
    const result = compare(before, after);
    expect(result.changes.find(row => row.domain === "evidence")?.kind).toBe("removed");
    const activity = result.changes.find(row => row.domain === "activities")!;
    expect(activity.evidenceBefore[0].quoted_text).toContain("optimized");
    expect(activity.evidenceAfter).toEqual([]);
    expect(result.changes.find(row => row.domain === "edge_evidence_links")?.evidenceBefore).toHaveLength(1);
  });
  it("includes unchanged unresolved issues and section not-reported transitions", () => {
    const before = snapshot(), after = snapshot();
    before.structures[0].status = after.structures[0].status = "unresolved";
    after.sections[5].state = "not_reported";
    const result = compare(before, after);
    expect(result.issues).toHaveLength(1);
    expect(result.changes.find(row => row.domain === "sections")?.fields[0].after).toBe("not_reported");
  });
  it("warns about absent baselines rather than reporting no modifications", () => {
    const result = buildComparison(snapshot(), undefined);
    expect(result.available).toBe(false);
    expect(result.warnings.length).toBeGreaterThan(0);
  });
  it("keeps bibliography changes and readable relation context", () => {
    const before = snapshot(), after = snapshot();
    after.paper.title = "Corrected title";
    after.lineage_edges[0].modification_summary = "Updated chemistry";
    const result = compare(before, after);
    expect(result.changes.map(row => row.domain)).toEqual(["paper", "lineage_edges"]);
    expect(result.changes[1].label).toContain("Lead 1 → Compound 18");
    expect(result.changes[1].evidenceBefore).toHaveLength(1);
  });
  it("ignores serialization-only chemistry changes only with consistent canonical identity", () => {
    const before = snapshot(), after = snapshot();
    after.structures[0].smiles = "OCC";
    after.structures[0].molfile = "Different coordinate layout";
    expect(compare(before, after).changes).toHaveLength(0);
    after.structures[0].inchikey = "DIFFERENT-STEREOCHEMISTRY";
    expect(compare(before, after).changes[0].fields.map(row => row.key)).toContain("inchikey");
    after.structures[0].canonical_smiles = null;
    expect(compare(before, after).changes[0].fields.map(row => row.key)).toContain("molfile");
  });
  it("attributes section changes by section key and keeps AI and admin contributors", () => {
    const before = snapshot(), after = snapshot();
    after.sections[5].state = "not_reported";
    const sectionEvent = {...reviewerEvent, entity_type: "paper_section_review", before_value: {section_key: "activities", state: "completed"}, after_value: {section_key: "activities", state: "not_reported"}};
    const result = compare(before, after, [{...sectionEvent, actor_kind: "ai"}, {...sectionEvent, actor_kind: "admin"}]);
    expect(result.changes[0].actors).toEqual(["ai", "admin"]);
  });

  it("normalizes legacy lineage defaults without hiding an actual lineage classification", () => {
    const before = snapshot(), after = snapshot();
    after.lineages[0].lineage_type = "unspecified";
    expect(compare(before, after).changes).toHaveLength(0);
    after.lineages[0].lineage_type = "sar";
    expect(compare(before, after).changes[0].fields[0].key).toBe("lineage_type");
  });

  it("compares decimal values and bbox coordinates losslessly across serialization formats", () => {
    const before = snapshot(), after = snapshot();
    before.evidence[0].x0 = "0.150000";
    after.evidence[0].x0 = "1.5e-1";
    before.activities[0].value = "125.000e-1";
    after.activities[0].value = 12.5;
    expect(compare(before, after).changes).toHaveLength(0);
    before.activities[0].value = "9007199254740992";
    after.activities[0].value = "9007199254740993";
    expect(compare(before, after).changes).toHaveLength(1);
  });

});

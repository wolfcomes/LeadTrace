import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import SubmissionComparison from "../src/approvals/SubmissionComparison.vue";
import FrozenEvidence from "../src/approvals/FrozenEvidence.vue";
import {
  frozenSnapshot,
  publicationIds as ids,
} from "./paper-publication-v2-fixtures";
import { setLocale } from "../src/i18n";
vi.stubGlobal(
  "IntersectionObserver",
  class {
    observe() {}
    disconnect() {}
  },
);
function props() {
  const before = structuredClone(frozenSnapshot);
  before.activities[0].value = "125";
  return {
    snapshot: frozenSnapshot,
    comparison: {
      kind: "previous_submission" as const,
      baseline_submission_number: 1,
      baseline_snapshot: before,
      events: [],
      warnings: [],
    },
    paperId: ids.paper,
  };
}
describe("complete approval record presentation", () => {
  it("shows one full changed compound with paired structure, assay context and visible evidence", async () => {
    setLocale("zh-CN");
    const wrapper = mount(SubmissionComparison, { props: props() });
    await wrapper.get('[data-record-tab="compounds"]').trigger("click");
    expect(wrapper.findAll("[data-record-entry]")).toHaveLength(1);
    const before = wrapper.get('[data-record-side="before"]'),
      after = wrapper.get('[data-record-side="after"]');
    expect(before.text()).toContain("125");
    expect(after.text()).toContain("12.5");
    expect(before.text()).toContain("Human cells");
    expect(after.text()).toContain("IC50");
    expect(wrapper.findAll("[data-evidence-thumbnail]")).toHaveLength(0);
    const structure = `[data-disclosure="structure:${ids.structureB}"]`;
    expect(before.get(structure).attributes("open")).toBeUndefined();
    expect(after.get(structure).attributes("open")).toBeUndefined();
    await before.get(`${structure} > summary`).trigger("click");
    expect(before.get(structure).attributes("open")).toBeDefined();
    expect(after.get(structure).attributes("open")).toBeDefined();
    expect(
      after
        .get(`[data-disclosure="activity:${ids.activity}"]`)
        .attributes("open"),
    ).toBeDefined();
    expect(
      after
        .get(`[data-disclosure="activity-context:${ids.activity}"]`)
        .attributes("open"),
    ).toBeUndefined();
    await wrapper.get("[data-change-only]").setValue(false);
    expect(wrapper.findAll("[data-record-entry]")).toHaveLength(2);
  });
  it("shows whole lineage with context even when only a member activity changed", async () => {
    const wrapper = mount(SubmissionComparison, {
      props: props(),
      global: { stubs: { FrozenLineageGraph: true } },
    });
    await wrapper.get('[data-record-tab="lineages"]').trigger("click");
    expect(wrapper.find("[data-lineage-comparison]").exists()).toBe(true);
    expect(wrapper.get("[data-record-entry]").text()).toContain("Series A");
    expect(wrapper.findAll("[data-lineage-relation]")).toHaveLength(1);
    expect(wrapper.find("[data-graph-mode]").exists()).toBe(false);
    expect(wrapper.find("[data-rdkit-depiction]").exists()).toBe(false);
  });
  it("mounts crops only after expansion, preserves no-region fallback and source mismatch", async () => {
    const base = {
      evidence: frozenSnapshot.evidence[0],
      snapshot: frozenSnapshot,
      paperId: ids.paper,
      currentSourceSha: frozenSnapshot.source.sha256,
    };
    const crop = mount(FrozenEvidence, { props: base });
    expect(crop.find("[data-evidence-thumbnail]").exists()).toBe(false);
    expect(crop.text()).not.toContain("未修改字段");
    await crop.get("[data-evidence-image] > summary").trigger("click");
    expect(crop.find("[data-evidence-thumbnail]").exists()).toBe(true);
    const noBox = mount(FrozenEvidence, {
      props: { ...base, evidence: { ...base.evidence, x0: null } },
    });
    expect(noBox.text()).toContain("未提供区域截图");
    const mismatch = mount(FrozenEvidence, {
      props: { ...base, currentSourceSha: "different" },
    });
    expect(mismatch.find("[data-evidence-thumbnail]").exists()).toBe(false);
  });
});

describe("outstanding issue navigation", () => {
  it("locates an unchanged unresolved relation inside its whole lineage", async () => {
    const values = props();
    const current = structuredClone(frozenSnapshot) as any;
    current.lineage_edges[0].review_hint = "Unchanged relation issue";
    values.snapshot = current;
    (values.comparison.baseline_snapshot.lineage_edges[0] as any).review_hint =
      "Unchanged relation issue";
    const wrapper = mount(SubmissionComparison, {
      props: values,
      global: { stubs: { FrozenLineageGraph: true } },
    });
    await wrapper.get("[data-remaining-issues] button").trigger("click");
    expect(
      wrapper.get('[data-record-tab="lineages"]').attributes("aria-pressed"),
    ).toBe("true");
    expect(
      wrapper.get("[data-lineage-relation]").attributes("aria-pressed"),
    ).toBe("true");
    expect(wrapper.get("[data-lineage-comparison]").text()).toContain(
      "Unchanged relation issue",
    );
    expect(wrapper.get(".relation-side").element.children.length).toBe(4);
    expect(
      wrapper
        .get(
          `[data-disclosure="relation:${ids.edge}"] [data-field="review_hint"]`,
        )
        .text(),
    ).toContain("Unchanged relation issue");
  });
  it("keeps an unchanged unresolved relation visible without a free-text hint", async () => {
    const values = props();
    values.snapshot = structuredClone(frozenSnapshot);
    values.snapshot.lineage_edges[0].review_status = "unresolved" as never;
    values.comparison.baseline_snapshot.lineage_edges[0].review_status =
      "unresolved" as never;
    const wrapper = mount(SubmissionComparison, {
      props: values,
      global: { stubs: { FrozenLineageGraph: true } },
    });
    await wrapper.get('[data-record-tab="lineages"]').trigger("click");
    await wrapper.get("[data-lineage-relation]").trigger("click");
    expect(
      wrapper
        .get(`[data-disclosure="relation:${ids.edge}"]`)
        .attributes("open"),
    ).toBeUndefined();
    expect(
      wrapper.get(`[data-disclosure="relation:${ids.edge}"] > summary`).text(),
    ).toContain("待核对");
    expect(wrapper.get(".relation-side").element.children.length).toBe(4);
  });
  it("locates an unchanged activity issue in the complete compound entry", async () => {
    const values = props(),
      current = structuredClone(frozenSnapshot) as any;
    current.activities[0].review_hint = "Unchanged assay issue";
    values.snapshot = current;
    (values.comparison.baseline_snapshot.activities[0] as any).review_hint =
      "Unchanged assay issue";
    const wrapper = mount(SubmissionComparison, { props: values });
    await wrapper.get("[data-remaining-issues] button").trigger("click");
    expect(
      wrapper.get('[data-record-tab="compounds"]').attributes("aria-pressed"),
    ).toBe("true");
    expect(wrapper.get('[data-record-side="after"]').text()).toContain(
      "Unchanged assay issue",
    );
  });
});

describe("lineage membership comparison", () => {
  it("shows a removed member as absent even while its global compound still exists", async () => {
    const values = props();
    values.snapshot = structuredClone(frozenSnapshot);
    values.snapshot.lineage_members = values.snapshot.lineage_members.filter(
      (x) => x.compound_id !== ids.compoundB,
    );
    values.snapshot.lineage_edges = [];
    const wrapper = mount(SubmissionComparison, {
      props: values,
      global: { stubs: { FrozenLineageGraph: true } },
    });
    await wrapper.get('[data-record-tab="lineages"]').trigger("click");
    await wrapper
      .get(`[data-lineage-member][data-compound-id="${ids.compoundB}"]`)
      .trigger("click");
    expect(wrapper.get('[data-record-side="before"]').text()).toContain(
      "Compound 18",
    );
    expect(wrapper.get('[data-record-side="after"]').text()).toContain(
      "本次提交已移出此 Lineage",
    );
    expect(wrapper.get('[data-record-side="after"]').text()).not.toContain(
      "Cell potency",
    );
  });
});

describe("nested comparison dialogs", () => {
  it("closes only the top evidence dialog on Escape and restores page scrolling", async () => {
    const wrapper = mount(SubmissionComparison, {
      props: props(),
      attachTo: document.body,
      global: { stubs: { FrozenLineageGraph: true, FrozenPdfCrop: true } },
    });
    await wrapper.get('[data-record-tab="lineages"]').trigger("click");
    await wrapper.get("[data-lineage-relation]").trigger("click");
    await wrapper.get("[data-graph-expand]").trigger("click");
    expect(
      wrapper.get("[data-lineage-comparison]").attributes("aria-modal"),
    ).toBe("true");
    await wrapper
      .findAll("[data-evidence-image] > summary")[0]
      .trigger("click");
    await wrapper.findAll("[data-enlarge-evidence]")[0].trigger("click");
    expect(document.querySelectorAll('[role="dialog"]')).toHaveLength(2);
    window.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
    );
    await wrapper.vm.$nextTick();
    expect(document.querySelectorAll('[role="dialog"]')).toHaveLength(1);
    expect(
      wrapper.get("[data-lineage-comparison]").attributes("aria-modal"),
    ).toBe("true");
    window.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
    );
    await wrapper.vm.$nextTick();
    expect(document.querySelectorAll('[role="dialog"]')).toHaveLength(0);
    expect(document.body.style.overflow).not.toBe("hidden");
    wrapper.unmount();
  });
});

describe("strict changed-content focus", () => {
  it("collapses unchanged measurements when only their evidence changed and puts activities first", async () => {
    const values = props();
    values.comparison.baseline_snapshot.activities[0].value =
      frozenSnapshot.activities[0].value;
    values.comparison.baseline_snapshot.evidence[0].quoted_text =
      "Old evidence";
    const wrapper = mount(SubmissionComparison, { props: values });
    const side = wrapper.get('[data-record-side="after"]');
    expect(
      side
        .get(`[data-disclosure="activity-result:${ids.activity}"]`)
        .attributes("open"),
    ).toBeUndefined();
    expect(
      side.get('[data-section="activities"]').attributes("data-priority"),
    ).toBe("0");
    expect(
      side.get('[data-section="structures"]').attributes("data-priority"),
    ).toBe("1");
    expect(
      side
        .get(`[data-disclosure="section:structures:${ids.compoundB}"]`)
        .attributes("open"),
    ).toBeUndefined();
  });
  it("does not expand unchanged depiction for a status-only structure resolution", async () => {
    const values = props();
    values.comparison.baseline_snapshot.structures[1].status =
      "unresolved" as never;
    const wrapper = mount(SubmissionComparison, { props: values });
    const side = wrapper.get('[data-record-side="after"]');
    expect(
      side
        .get(`[data-disclosure="structure-depiction:${ids.structureB}"]`)
        .attributes("open"),
    ).toBeUndefined();
    expect(
      side
        .get(
          `[data-review-fields="structures:${ids.structureB}"] [data-field="status"]`,
        )
        .text(),
    ).toContain("已确认");
  });
  it("keeps unchanged unresolved content collapsed with a visible summary badge", async () => {
    const values = props();
    values.snapshot = structuredClone(frozenSnapshot);
    Object.assign(values.snapshot.activities[0], {
      review_hint: "Still check this",
    });
    values.comparison.baseline_snapshot.activities[0] = structuredClone(
      values.snapshot.activities[0],
    );
    values.comparison.baseline_snapshot.compounds[1].description =
      "Changed description";
    const wrapper = mount(SubmissionComparison, { props: values });
    const disclosure = wrapper.get(
      `[data-disclosure="activity:${ids.activity}"]`,
    );
    expect(disclosure.attributes("open")).toBeUndefined();
    expect(disclosure.get("summary").text()).toContain("待核对");
  });
});

describe("member changes are local to the selected lineage", () => {
  it("opens changed membership detail but leaves global compound identity closed", async () => {
    const values = props();
    values.comparison.baseline_snapshot.activities[0].value =
      frozenSnapshot.activities[0].value;
    values.comparison.baseline_snapshot.lineage_members[1].role =
      "root" as never;
    const wrapper = mount(SubmissionComparison, {
      props: values,
      global: { stubs: { FrozenLineageGraph: true } },
    });
    await wrapper.get('[data-record-tab="lineages"]').trigger("click");
    await wrapper
      .get(`[data-lineage-member][data-compound-id="${ids.compoundB}"]`)
      .trigger("click");
    expect(
      wrapper
        .get(`[data-disclosure="section:identity:${ids.compoundB}"]`)
        .attributes("open"),
    ).toBeDefined();
    await wrapper.get("[data-change-only]").setValue(false);
    await wrapper.get('[data-record-tab="compounds"]').trigger("click");
    await wrapper
      .get(`[data-record-entry="${ids.compoundB}"]`)
      .trigger("click");
    expect(
      wrapper
        .get(`[data-disclosure="section:identity:${ids.compoundB}"]`)
        .attributes("open"),
    ).toBeUndefined();
  });
});


it("places changed source evidence before unchanged source occurrences on both sides", () => {
  const values=props(); values.snapshot=structuredClone(frozenSnapshot);
  const image={...values.snapshot.structure_source_images[0],compound_id:ids.compoundB};
  const first={...image,id:'unchanged-image'}, second={...image,id:'changed-image'};
  values.snapshot.structure_source_images=[first,{...second,page_number:8}];
  values.comparison.baseline_snapshot.structure_source_images=[structuredClone(first),second];
  const wrapper=mount(SubmissionComparison,{props:values});
  for(const side of ['before','after']) {
    expect(wrapper.get(`[data-record-side="${side}"] [data-section="originals"] [data-frozen-evidence]`).attributes('data-evidence-id')).toBe('changed-image');
  }
});

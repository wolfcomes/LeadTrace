import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import FrozenEvidence from "../src/approvals/FrozenEvidence.vue";
import SubmissionComparison from "../src/approvals/SubmissionComparison.vue";
import { frozenSnapshot, reviewerEvent } from "./paper-publication-v2-fixtures";
import { setLocale } from "../src/i18n";
function props() {
  const baseline = structuredClone(frozenSnapshot);
  baseline.activities[0].value = "125";
  baseline.evidence[0].quoted_text = "Original quoted evidence";
  return { snapshot: frozenSnapshot, comparison: { kind: "previous_submission" as const, baseline_submission_number: 1, baseline_snapshot: baseline, events: [reviewerEvent], warnings: [] }, paperId: frozenSnapshot.paper.id };
}
describe("changes-first approval presentation", () => {
  it("shows grouped before/after scientific values and frozen evidence context without JSON as primary content", () => {
    setLocale("zh-CN");
    const wrapper = mount(SubmissionComparison, {props: props()});
    expect(wrapper.get("[data-comparison-summary]").text()).toContain("第 1 次提交");
    expect(wrapper.findAll("[data-change-card]")).toHaveLength(1);
    expect(wrapper.text()).toContain("125");
    expect(wrapper.text()).toContain("12.5");
    expect(wrapper.text()).toContain("Original quoted evidence");
    expect(wrapper.text()).toContain("Lead 1 was optimized to compound 18.");
    expect(wrapper.findAll("pre")).toHaveLength(0);
    expect(wrapper.findAll('img[src*="structure-source-images"]')).toHaveLength(0);
  });
  it("keeps ordinary confirmations collapsed and renders warnings in both languages", () => {
    const values = props();
    values.comparison.baseline_snapshot = structuredClone(frozenSnapshot);
    values.comparison.baseline_snapshot.structures[0].status = "ai_draft" as never;
    const wrapper = mount(SubmissionComparison, {props: values});
    expect(wrapper.findAll("[data-change-card]")).toHaveLength(0);
    expect(wrapper.get("[data-confirmation-summary]").attributes("open")).toBeUndefined();
    wrapper.unmount();
    setLocale("en");
    const missing = mount(SubmissionComparison, { props: {snapshot: frozenSnapshot, paperId: frozenSnapshot.paper.id} });
    expect(missing.get("[data-comparison-warning]").text()).toContain("baseline");
    expect(missing.text()).not.toContain("No substantive changes");
    setLocale("zh-CN");
  });
  it("does not load a current PDF as historical evidence when its source fingerprint differs", () => {
    const wrapper = mount(FrozenEvidence, {props: {evidence: frozenSnapshot.evidence[0], snapshot: frozenSnapshot, paperId: frozenSnapshot.paper.id, currentSourceSha: "b".repeat(64)}});
    expect(wrapper.find("a").exists()).toBe(false);
    expect(wrapper.find("[data-evidence-image]").exists()).toBe(false);
    expect(wrapper.find("[data-evidence-thumbnail]").exists()).toBe(false);
    expect(wrapper.get("[data-disclosure]").attributes("open")).toBeUndefined();
    expect(wrapper.get(".message.is-error").isVisible()).toBe(true);
    expect(wrapper.text()).toContain("证据来源与冻结 PDF 不一致");
  });

  it("explains unresolved-to-confirmed transitions with readable bilingual labels", async () => {
    const values = props();
    values.comparison.baseline_snapshot.structures[0].status = "unresolved" as never;
    const wrapper = mount(SubmissionComparison, {props: values});
    await wrapper.get(`[data-record-entry="${frozenSnapshot.compounds[0].id}"]`).trigger('click');
    const before = wrapper.get('[data-record-side="before"]');
    const after = wrapper.get('[data-record-side="after"]');
    expect(before.text()).toContain("未解决");
    expect(after.text()).toContain("已确认");
    expect(after.text()).not.toContain("reviewer_confirmed");
  });

});

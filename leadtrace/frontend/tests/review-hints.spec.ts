import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ReviewHint from "../src/review/paper/ReviewHint.vue";
import ActivityEditor from "../src/review/paper/ActivityEditor.vue";
import CompoundList from "../src/review/paper/CompoundList.vue";
import EdgeEditor from "../src/review/paper/EdgeEditor.vue";
import { compoundSchema, activitySchema, lineageEdgeSchema, lineageRecordSchema, paperWorkspaceSchema } from "../src/v2/types";
import { compounds, edges, lineages, installReviewer, activities, workspace, response, ids } from "./paper-science-v2-fixtures";

describe("simple review hints", () => {
  beforeEach(installReviewer);
  afterEach(() => vi.unstubAllGlobals());
  it("uses an accessible disclosure and renders scientific text safely", async () => {
    const hint = '<img src=x onerror="alert(1)"> Table 1 differs from the text.';
    const wrapper = mount(ReviewHint, { props: { hint } });
    const button = wrapper.get("button");
    expect(button.text()).toBe("⚠");
    expect(button.attributes("type")).toBe("button");
    expect(button.attributes("aria-label")).toBe("需核对");
    expect(button.attributes("aria-expanded")).toBe("false");
    expect(wrapper.find("[role=note]").exists()).toBe(false);
    await button.trigger("click");
    expect(button.attributes("aria-expanded")).toBe("true");
    expect(wrapper.get("[role=note]").text()).toBe(hint);
    expect(wrapper.get("[role=note]").attributes("id")).toBe(button.attributes("aria-controls"));
    expect(wrapper.find("img").exists()).toBe(false);
    await button.trigger("click");
    expect(wrapper.find("[role=note]").exists()).toBe(false);
    await wrapper.setProps({ hint: "  " });
    expect(wrapper.find("button").exists()).toBe(false);
  });
  it("preserves hints on response records and accepts old responses", () => {
    for (const [schema, row] of [[compoundSchema, compounds[0]], [lineageEdgeSchema, edges[0]]] as const) {
      expect(schema.parse({ ...row, review_hint: "Check correspondence" }).review_hint).toBe("Check correspondence");
      expect(schema.parse(row).review_hint).toBeUndefined();
    }
    const activity = { id: compounds[0].id, paper_id: compounds[0].paper_id, workspace_id: compounds[0].workspace_id,
      compound_id: compounds[0].id, evidence_id: null, assay_name: "Test assay", metric: "IC50", operator: "=", value: "12", unit: "nM", context: null, sort_order: 0 };
    expect(activitySchema.parse({ ...activity, review_hint: "Values conflict" }).review_hint).toBe("Values conflict");
  });
  it("keeps hints when confirming an edge and clears only through explicit editing", async () => {
    const edge = lineageEdgeSchema.parse({ ...edges[0], review_hint: "Source-supported family correspondence; check pairing" });
    const wrapper = mount(EdgeEditor, { props: { lineage: lineageRecordSchema.parse({ ...lineages[0], edges: [edge] }), compounds: compounds.map(item => compoundSchema.parse(item)) } });
    expect(wrapper.findComponent(ReviewHint).props("hint")).toBe(edge.review_hint);
    await wrapper.get(".edge-row select").setValue("reviewer_confirmed");
    expect(wrapper.emitted("update")?.[0]?.[1]).toEqual({ reviewStatus: "reviewer_confirmed" });
    await wrapper.get("[data-edit-edge]").trigger("click");
    expect((wrapper.get("[data-edit-edge-review-hint]").element as HTMLInputElement).value).toBe(edge.review_hint);
    await wrapper.get("[data-edit-edge-review-hint]").setValue("");
    await wrapper.get("[data-save-edge-edit]").trigger("click");
    expect(wrapper.emitted("update")?.[1]?.[1]).toMatchObject({ reviewHint: null });
    await wrapper.setProps({ readOnly: true });
    await flushPromises();
    expect(wrapper.get("[data-edit-edge]").attributes("disabled")).toBeDefined();
    await wrapper.get("[data-review-hint] button").trigger("click");
    expect(wrapper.get("[role=note]").text()).toBe(edge.review_hint);
  });
});


describe("review hint editing", () => {
  beforeEach(installReviewer);
  afterEach(() => vi.unstubAllGlobals());
  it.each(["compound", "activity"] as const)("clears a %s hint using its existing versioned edit", async (kind) => {
    const compound = { ...compounds[0], review_hint: "Shared core; check closure" };
    const activity = { ...activities[0], review_hint: "Table and text conflict" };
    const writes: Record<string, unknown>[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (init?.method === "PATCH") {
        const body = JSON.parse(String(init.body));
        writes.push(body);
        const { expected_workspace_version, ...fields } = body;
        expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("reviewer-csrf");
        return response({ [kind]: { ...(kind === "compound" ? compound : activity), ...fields }, workspace_version: expected_workspace_version + 1 });
      }
      if (path.endsWith("/compounds")) return response({ workspace_id: ids.workspace, workspace_version: 1, items: [compound], total: 1 });
      if (path.endsWith("/activities")) return response({ compound_id: compound.id, workspace_version: 1, items: [activity], total: 1 });
      if (path.endsWith("/evidence")) return response({ workspace_id: ids.workspace, workspace_version: 1, items: [], total: 0 });
      throw new Error(path);
    }));
    const props = { workspace: paperWorkspaceSchema.parse(workspace()) };
    const wrapper = kind === "compound"
      ? mount(CompoundList, { props, global: { stubs: { CompoundStructureEditor: true, ActivityEditor: true } } })
      : mount(ActivityEditor, { props });
    await flushPromises();
    expect(wrapper.get("[data-review-hint] button").text()).toBe("⚠");
    await wrapper.get('[data-edit-' + kind + ']').trigger("click");
    await wrapper.get('[data-edit-' + kind + '-review-hint]').setValue("");
    await wrapper.get(kind === "compound" ? "[data-save-compound]" : "[data-save-activity-edit]").trigger("click");
    await flushPromises();
    expect(writes).toHaveLength(1);
    expect(writes[0]).toMatchObject({ expected_workspace_version: 1, review_hint: null });
    expect(wrapper.find("[data-review-hint]").exists()).toBe(false);
    expect(wrapper.emitted("mutated")).toEqual([[2]]);
    wrapper.unmount();
  });
});

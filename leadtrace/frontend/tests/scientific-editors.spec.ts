import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import ActivityEditor from "../src/activities/ActivityEditor.vue";
import CompoundEditor from "../src/compounds/CompoundEditor.vue";
import EvidenceEditor from "../src/evidence/EvidenceEditor.vue";
import LineageEditor from "../src/lineages/LineageEditor.vue";
import ScientificEditors from "../src/review/changesets/ScientificEditors.vue";

describe("scientific review editors", () => {
  it("keeps original evidence text and stable compound references", async () => {
    const wrapper = mount(EvidenceEditor, {
      props: {
        modelValue: {
          evidenceKey: "ev-1",
          originalText: "Compound 3 showed improved potency.",
          sourceLocator: "Table 1",
          compoundIds: ["compound-1"],
          reason: "",
        },
        editable: true,
      },
    });

    expect(wrapper.get("form").classes()).toEqual(expect.arrayContaining(["editor-form", "panel"]));
    expect(wrapper.findAll("label.form-field")).toHaveLength(4);
    expect(wrapper.get("button[type='submit']").classes()).toContain("button-primary");
    expect(wrapper.get("textarea[name='original-text']").element).toHaveProperty(
      "value",
      "Compound 3 showed improved potency.",
    );
    await wrapper.get("input[name='reason']").setValue("Corrected source locator");
    expect(wrapper.get("button[type='submit']").attributes("disabled")).toBeUndefined();
  });

  it("renders assay metric value unit and qualifier as separate controls", () => {
    const wrapper = mount(ActivityEditor, {
      props: {
        modelValue: {
          activityKey: "assay-1",
          assay: "cAMP accumulation",
          metric: "pEC50",
          value: "7.4",
          unit: "nM",
          qualifier: "=",
          evidenceText: "Original assay text",
          reason: "review",
        },
        editable: true,
      },
    });

    expect(wrapper.get("form").classes()).toEqual(expect.arrayContaining(["editor-form", "panel"]));
    expect(wrapper.findAll("[data-activity-field].form-field")).toHaveLength(5);
    expect(wrapper.findAll("[data-activity-field]")).toHaveLength(5);
  });

  it("does not expose a pair-ready input in the lineage editor", () => {
    const wrapper = mount(LineageEditor, {
      props: {
        modelValue: {
          lineageKey: "L1",
          parentCompoundId: null,
          derivedCompoundId: "compound-2",
          relationType: "optimization",
          relationStatus: "unresolved",
          evidenceIds: [],
          reason: "review",
        },
        readiness: { eligible: false, blockingCodes: ["UNRESOLVED_PARENT"] },
        editable: true,
      },
    });

    expect(wrapper.find("input[name='pair-ready']").exists()).toBe(false);
    expect(wrapper.get("[data-pair-readiness]").classes()).toContain("status-chip");
    expect(wrapper.get("[data-pair-readiness]").text()).toContain("UNRESOLVED_PARENT");
  });

  it("requires a reason before creating a Paper-local compound", async () => {
    const wrapper = mount(CompoundEditor, {
      props: {
        modelValue: { localIdentity: "26b", displayLabel: "26b", reason: "" },
        editable: true,
      },
    });

    expect(wrapper.get("form").classes()).toEqual(expect.arrayContaining(["editor-form", "panel"]));
    expect(wrapper.get("button[type='submit']").attributes("disabled")).toBeDefined();
    await wrapper.get("textarea[name='reason']").setValue("New label appears in Table S3");
    expect(wrapper.get("button[type='submit']").attributes("disabled")).toBeUndefined();
  });

  it("maps direct scientific snapshots into the changeset workspace", async () => {
    const wrapper = mount(ScientificEditors, {
      props: {
        items: [{
          id: "70000000-0000-4000-8000-000000000001",
          changeset_id: "60000000-0000-4000-8000-000000000001",
          paper_id: "20000000-0000-4000-8000-000000000001",
          object_id: "71000000-0000-4000-8000-000000000001",
          object_kind: "compound",
          base_revision_id: null,
          proposed_revision_id: null,
          proposed_snapshot: { local_identity: "26b", display_label: "26b" },
          content_hash: "a".repeat(64),
          sequence: 1,
          changeset_version: 2,
          created_at: "2026-09-12T01:00:00Z",
        }],
        editable: true,
        reason: "review",
      },
    });

    await wrapper.get("input[name='display-label']").setValue("26b corrected");
    await wrapper.get("input[name='local-identity']").setValue("26b-main");
    const updates = wrapper.emitted("update");
    expect(updates).toBeTruthy();
    expect(updates?.at(-1)?.[1]).toMatchObject({ local_identity: "26b-main", display_label: "26b corrected" });
  });

  it("hands visual and chemistry objects to the typed Paper workspace", () => {
    const base = {
      id: "70000000-0000-4000-8000-000000000002",
      changeset_id: "60000000-0000-4000-8000-000000000001",
      paper_id: "20000000-0000-4000-8000-000000000001",
      base_revision_id: null,
      proposed_revision_id: null,
      proposed_snapshot: {},
      content_hash: "b".repeat(64),
      sequence: 2,
      changeset_version: 2,
      created_at: "2026-09-12T01:00:00Z",
    };
    const wrapper = mount(ScientificEditors, {
      props: {
        items: [
          { ...base, object_id: "71000000-0000-4000-8000-000000000001", object_kind: "visual_region" },
          { ...base, id: "70000000-0000-4000-8000-000000000003", object_id: "71000000-0000-4000-8000-000000000002", object_kind: "molecule_proposal", sequence: 3 },
        ],
        editable: true,
        reason: "review",
      },
    });

    expect(wrapper.findAll("[data-specialized-handoff]")).toHaveLength(2);
    expect(wrapper.find("a[href*='view=pdf']").attributes("href")).toContain("region=71000000-0000-4000-8000-000000000001");
    expect(wrapper.find("a[href*='view=ocsr']").attributes("href")).toContain("proposal=71000000-0000-4000-8000-000000000002");
    expect(wrapper.find("[data-specialized-handoff] textarea").exists()).toBe(false);
  });
});

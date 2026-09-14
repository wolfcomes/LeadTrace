import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import StructureComparison from "../src/structures/StructureComparison.vue";
import StructureEditor from "../src/structures/StructureEditor.vue";

describe("source-aware structure review", () => {
  it("labels RDKit success as parseable and requires source plus reason", async () => {
    const wrapper = mount(StructureEditor, {
      props: {
        modelValue: {
          smiles: "CCO",
          source: "",
          reason: "",
          structureState: "parseable_candidate",
        },
        validation: { parseable: true, messages: [], componentCount: 1 },
        editable: true,
      },
    });

    expect(wrapper.get("form").classes()).toEqual(expect.arrayContaining(["editor-form", "panel"]));
    expect(wrapper.get("[data-parse-status]").classes()).toContain("status-chip");
    expect(wrapper.findAll("label.form-field").length).toBeGreaterThanOrEqual(3);
    expect(wrapper.get("button[type='submit']").classes()).toContain("button-primary");
    expect(wrapper.get("[data-parse-status]").text()).toBe("RDKit 可解析");
    expect(wrapper.get("button[type='submit']").attributes("disabled")).toBeDefined();

    await wrapper.get("[name='source']").setValue("SI, Table S2");
    await wrapper.get("[name='reason']").setValue("人工核对来源结构");
    expect(wrapper.get("button[type='submit']").attributes("disabled")).toBeUndefined();
  });

  it("compares published and draft drawings without requiring smiles for non-unique material", () => {
    const wrapper = mount(StructureComparison, {
      props: {
        published: { label: "已发布", imageUrl: "/published.png", smiles: "CCO" },
        draft: {
          label: "草稿",
          imageUrl: null,
          smiles: null,
          structureState: "non_unique_stereochemistry",
        },
      },
    });

    expect(wrapper.findAll("[data-structure-side]")).toHaveLength(2);
    expect(wrapper.findAll("[data-structure-side].panel")).toHaveLength(2);
    expect(wrapper.get("[data-structure-side] .status-chip").text()).toContain("非唯一立体化学");
    expect(wrapper.text()).toContain("非唯一立体化学");
  });
});

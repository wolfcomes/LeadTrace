import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import ObjectInspector from "../src/visual-objects/ObjectInspector.vue";
import CompoundBindings from "../src/visual-objects/CompoundBindings.vue";
import ImageBindings from "../src/visual-objects/ImageBindings.vue";

describe("molecule object review controls", () => {
  it("emits a controlled semantic type change", async () => {
    const wrapper = mount(ObjectInspector, {
      props: {
        object: { id: "object-1", objectKey: "mol-1", objectType: "r_group", label: "R1" },
        editable: true,
      },
    });

    await wrapper.get("select").setValue("linker");
    expect(wrapper.emitted("update-type")).toEqual([["linker"]]);
  });

  it("keeps every compound label as a separate binding row", () => {
    const wrapper = mount(CompoundBindings, {
      props: {
        bindings: [
          { id: "b1", compoundId: "c1", label: "26a", role: "primary" },
          { id: "b2", compoundId: "c1", label: "26a'", role: "alternate" },
        ],
      },
    });

    expect(wrapper.findAll("[data-compound-binding]")).toHaveLength(2);
    expect(wrapper.text()).toContain("26a'");
  });

  it("shows that one crop asset can be reused by multiple objects", () => {
    const wrapper = mount(ImageBindings, {
      props: {
        assets: [{ id: "asset-1", filename: "crop.png", objectCount: 3, primary: true }],
      },
    });

    expect(wrapper.get("[data-image-binding='asset-1']").text()).toContain("3");
  });
});

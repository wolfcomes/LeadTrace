import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ObjectInspector from "../src/visual-objects/ObjectInspector.vue";
import CompoundBindings from "../src/visual-objects/CompoundBindings.vue";
import ImageBindings from "../src/visual-objects/ImageBindings.vue";
import VisualObjectInspector from "../src/review/workspace/VisualObjectInspector.vue";
import {
  bindVisualObjectAsset,
  bindVisualObjectCompound,
  bindVisualObjectRegion,
  removeVisualObjectBinding,
  updateVisualObject,
} from "../src/review/api";
import { useAuthStore } from "../src/auth/store";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("molecule object review controls", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    useAuthStore().acceptSession({
      user: { username: "reviewer.one", display_name: "Reviewer", role: "reviewer", must_change_password: false },
      csrf_token: "csrf-token",
    });
  });
  it("emits a controlled semantic type change", async () => {
    const wrapper = mount(ObjectInspector, {
      props: {
        object: { id: "object-1", objectKey: "mol-1", objectType: "r_group", label: "R1" },
        editable: true,
      },
    });

    expect(wrapper.get(".object-inspector").classes()).toContain("panel");
    expect(wrapper.findAll("label.form-field")).toHaveLength(2);
    expect(wrapper.get("select").classes()).toContain("form-control");
    await wrapper.get("select").setValue("linker");
    expect(wrapper.emitted("update-type")).toEqual([["linker"]]);
  });

  it("keeps every compound label as a separate binding row", () => {
    const wrapper = mount(CompoundBindings, {
      props: {
        bindings: [
          { id: "b1", compoundId: "c1", label: "26a", role: "primary", operation: "add" },
          { id: "b2", compoundId: "c1", label: "26a'", role: "alternate" },
        ],
      },
    });

    expect(wrapper.get(".binding-panel").classes()).toContain("panel");
    expect(wrapper.findAll("[data-compound-binding]")).toHaveLength(2);
    expect(wrapper.get("[data-binding-operation]").classes()).toContain("status-chip");
    expect(wrapper.text()).toContain("26a'");
  });

  it("shows that one crop asset can be reused by multiple objects", () => {
    const wrapper = mount(ImageBindings, {
      props: {
        assets: [{ id: "asset-1", filename: "crop.png", objectCount: 3, primary: true }],
      },
    });

    expect(wrapper.get(".binding-panel").classes()).toContain("panel");
    expect(wrapper.get("[data-image-binding='asset-1']").text()).toContain("3");
  });

  it("shows typed object fields, binding operations, primary crop, and source jump", async () => {
    const visual = {
      id: "10000000-0000-4000-8000-000000000001",
      object_key: "object-1",
      object_type: "complete_molecule" as const,
      revision_id: "10000000-0000-4000-8000-000000000002",
      snapshot: { label: "Lead 26a" },
      queue_state: "source_or_attachment" as const,
      blocking: true,
      region_id: "10000000-0000-4000-8000-000000000003",
      bindings: {
        regions: [{ id: "rb-1", region_id: "10000000-0000-4000-8000-000000000003", role: "source", operation: "add" }],
        assets: [{
          id: "ab-1",
          asset_id: "10000000-0000-4000-8000-000000000004",
          role: "crop",
          is_primary: true,
          operation: "update",
          asset: { original_filename: "crop.png" },
        }],
        compounds: [{ id: "cb-1", compound_id: "compound-1", label: "26a", role: "primary", confidence: 0.9 }],
        relations: [],
      },
    };
    const wrapper = mount(VisualObjectInspector, {
      props: {
        visual,
        regions: [{ id: visual.region_id, label: "region-1" }],
        assets: [{ id: "10000000-0000-4000-8000-000000000004", filename: "crop.png" }],
        editable: true,
        hasSourceLocator: true,
      },
    });

    expect(wrapper.get("[data-object-label]").element).toHaveProperty("value", "Lead 26a");
    expect(wrapper.get("[data-primary-crop]").text()).toContain("crop.png");
    expect(wrapper.get("[data-region-binding]").text()).toContain("source");
    expect(wrapper.get("[data-binding-operation]").text()).toContain("修改");
    expect(wrapper.find("textarea").exists()).toBe(false);

    await wrapper.get("[data-source-locator]").trigger("click");
    expect(wrapper.emitted("locate-source")?.[0]).toEqual([visual.region_id]);
    await wrapper.get("select[data-object-type]").setValue("shared_scaffold");
    await wrapper.get("[data-save-object]").trigger("click");
    expect(wrapper.emitted("save")?.[0]).toEqual([{
      object_type: "shared_scaffold",
      label: "Lead 26a",
    }]);
  });

  it("uses typed visual-object and binding API operations", async () => {
    const calls: Array<{ path: string; method?: string; body?: unknown }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      calls.push({ path, method: init?.method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      if (path.endsWith("/visual-objects/object-1")) {
        return jsonResponse({
          id: "10000000-0000-4000-8000-000000000001",
          paper_id: "10000000-0000-4000-8000-000000000002",
          object_key: "object-1",
          object_type: "shared_scaffold",
          revision_id: "10000000-0000-4000-8000-000000000003",
          revision_number: 2,
          changeset_id: "10000000-0000-4000-8000-000000000004",
          changeset_version: 4,
          snapshot: { object_key: "object-1", object_type: "shared_scaffold" },
          workflow_state: "draft",
        });
      }
      if (init?.method === "DELETE") return jsonResponse({ id: "binding-1", operation: "remove" });
      return jsonResponse({ id: "binding-1" });
    }));

    const context = { changeset_id: "changeset-1", expected_version: 3 };
    await updateVisualObject("paper-1", "object-1", { ...context, object_type: "shared_scaffold", label: "Core" });
    await bindVisualObjectRegion("paper-1", "object-1", { ...context, region_id: "region-1", role: "source" });
    await bindVisualObjectAsset("paper-1", "object-1", { ...context, asset_id: "asset-1", role: "crop", is_primary: true });
    await bindVisualObjectCompound("paper-1", "object-1", { ...context, compound_id: "compound-1", label: "26a", role: "primary" });
    await removeVisualObjectBinding("paper-1", "object-1", "assets", "binding-1", context);

    expect(calls.map((call) => [call.method, call.path])).toEqual([
      ["PATCH", "/api/v1/papers/paper-1/visual-objects/object-1"],
      ["POST", "/api/v1/papers/paper-1/visual-objects/object-1/regions"],
      ["POST", "/api/v1/papers/paper-1/visual-objects/object-1/assets"],
      ["POST", "/api/v1/papers/paper-1/visual-objects/object-1/compounds"],
      ["DELETE", "/api/v1/papers/paper-1/visual-objects/object-1/assets/binding-1"],
    ]);
    expect(calls.every((call) => (call.body as Record<string, unknown>).changeset_id === "changeset-1")).toBe(true);
  });
});

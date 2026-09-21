import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ActivityEditor from "../src/review/paper/ActivityEditor.vue";
import type { PaperWorkspace } from "../src/v2/types";
import { activities, compounds, ids, installReviewer, response, workspace } from "./paper-science-v2-fixtures";

function setup(count = 57, selectedEntityId?: string) {
  let rows = Array.from({ length: count }, (_, index) => ({ ...activities[0],
    id: `90000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
    compound_id: ids.compounds[index < 30 ? 0 : 1], assay_name: `Assay ${index + 1}`, sort_order: index,
  }));
  let version = 1;
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), "http://leadtrace.test").pathname;
    if (init?.method === "PATCH") {
      const body = JSON.parse(String(init.body));
      rows = rows.map((row) => path.endsWith(row.id) ? { ...row, value: body.value } : row);
      return response({ activity: rows.find((row) => path.endsWith(row.id)), workspace_version: ++version });
    }
    if (init?.method === "DELETE") {
      const id = path.split("/").at(-1); rows = rows.filter((row) => row.id !== id);
      return response({ deleted_activity_id: id, workspace_version: ++version });
    }
    if (init?.method === "POST") {
      const { expected_workspace_version: _expected, ...payload } = JSON.parse(String(init.body));
      const row = { ...activities[0], ...payload, id: "90000000-0000-4000-8000-000000000999", compound_id: path.split("/")[4] };
      rows.push(row); return response({ activity: row, workspace_version: ++version });
    }
    if (path.endsWith("/compounds")) return response({ items: compounds, total: compounds.length, workspace_id: ids.workspace, workspace_version: version });
    if (path.endsWith("/evidence")) return response({ items: [], total: 0, workspace_id: ids.workspace, workspace_version: version });
    const compoundId = path.split("/")[4]; const items = rows.filter((row) => row.compound_id === compoundId);
    return response({ compound_id: compoundId, items, total: items.length, workspace_version: version });
  });
  vi.stubGlobal("fetch", fetcher);
  return { wrapper: mount(ActivityEditor, { props: { workspace: workspace() as PaperWorkspace, selectedEntityId } }), fetcher };
}
beforeEach(installReviewer);
afterEach(() => vi.unstubAllGlobals());

describe("Activity filtering and pagination", () => {
  it("shows every record exactly once over 25-row pages and resets compound filtering", async () => {
    const { wrapper, fetcher } = setup(); await flushPromises();
    expect(wrapper.findAll("[data-activity-row]")).toHaveLength(25);
    expect(wrapper.get("[data-activity-count]").text()).toContain("共 57 条");
    const seen = wrapper.findAll("[data-activity-row]").map((row) => row.attributes("data-activity-id"));
    await wrapper.get("[data-activity-next]").trigger("click");
    seen.push(...wrapper.findAll("[data-activity-row]").map((row) => row.attributes("data-activity-id")));
    await wrapper.get("[data-activity-next]").trigger("click");
    seen.push(...wrapper.findAll("[data-activity-row]").map((row) => row.attributes("data-activity-id")));
    expect(seen).toHaveLength(57); expect(new Set(seen).size).toBe(57);
    expect(wrapper.get("[data-activity-next]").attributes("disabled")).toBeDefined();
    await wrapper.get("[data-activity-filter]").setValue(ids.compounds[1]);
    expect(wrapper.get("[data-activity-count]").text()).toContain("筛选后 27 条");
    expect(wrapper.get("[data-activity-page]").text()).toContain("1 / 2");
    expect(wrapper.findAll("[data-activity-row]").every((row) => row.get("strong").text() === "C2")).toBe(true);
    await wrapper.get("[data-activity-filter]").setValue(ids.compounds[2]);
    expect(wrapper.text()).toContain("该化合物暂无 Activity");
    await wrapper.get("[data-activity-filter]").setValue("");
    expect(wrapper.findAll("[data-activity-row]")).toHaveLength(25);
    expect(fetcher).toHaveBeenCalledTimes(6);
  });
  it("opens the selected record page and reveals a deep link hidden by the filter", async () => {
    const target = "90000000-0000-4000-8000-000000000057";
    const { wrapper } = setup(57, target); await flushPromises();
    expect(wrapper.get("[data-activity-page]").text()).toContain("3 / 3");
    expect(wrapper.get("[data-activity-row].selected").attributes("data-activity-id")).toBe(target);
    await wrapper.get("[data-activity-filter]").setValue(ids.compounds[0]);
    await wrapper.setProps({ selectedEntityId: "90000000-0000-4000-8000-000000000056" }); await flushPromises();
    expect(wrapper.get("[data-activity-filter]").element).toHaveProperty("value", "");
    expect(wrapper.get("[data-activity-row].selected").text()).toContain("Assay 56");
  });
  it("edits and deletes the last-page record then clamps to a populated page", async () => {
    const { wrapper, fetcher } = setup(26); await flushPromises();
    await wrapper.get("[data-activity-next]").trigger("click");
    await wrapper.get("[data-edit-activity]").trigger("click");
    await wrapper.get("[data-edit-activity-value]").setValue("42");
    await wrapper.get("[data-save-activity-edit]").trigger("click"); await flushPromises();
    expect(wrapper.get("[data-activity-row]").text()).toContain("42");
    await wrapper.get("[data-activity-row]").findAll("button")[1]!.trigger("click"); await flushPromises();
    expect(wrapper.findAll("[data-activity-row]")).toHaveLength(25);
    expect(wrapper.get("[data-activity-page]").text()).toContain("1 / 1");
    expect(fetcher.mock.calls.filter((call) => call[1]?.method).map((call) => call[1]?.method)).toEqual(["PATCH", "DELETE"]);
  });
  it("reveals a new activity even when another compound is filtered", async () => {
    const { wrapper } = setup(); await flushPromises();
    await wrapper.get("[data-activity-filter]").setValue(ids.compounds[1]);
    await wrapper.get("[data-add-activity]").trigger("click");
    const form = wrapper.get(".activity-create-form");
    await form.get("input[maxlength='512']").setValue("New assay");
    await form.get("input[inputmode='decimal']").setValue("18");
    await form.get("button").trigger("click"); await flushPromises();
    expect(wrapper.findAll("[data-activity-row]").some((row) => row.text().includes("New assay"))).toBe(true);
    expect(wrapper.get("[data-activity-count]").text()).toContain("共 58 条");
  });
});

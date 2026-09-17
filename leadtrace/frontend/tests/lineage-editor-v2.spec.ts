import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { compounds, edges, ids, installReviewer, lineages, mountWorkspace, response, workspace } from "./paper-science-v2-fixtures";


describe("Lineage editor", () => {
  beforeEach(installReviewer);
  afterEach(() => vi.unstubAllGlobals());

  it("shows multiple Lineages, multiple roots and terminals, and a read-only branching graph", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://leadtrace.test");
      if (url.pathname.endsWith("/compounds")) return response({ workspace_id: ids.workspace, workspace_version: 1, items: compounds, total: compounds.length });
      if (url.pathname.endsWith("/lineages")) return response({ workspace_id: ids.workspace, workspace_version: 1, items: lineages, total: lineages.length });
      return response(workspace());
    }));

    const { wrapper } = await mountWorkspace("lineages");

    expect(wrapper.findAll("[data-lineage-card]")).toHaveLength(2);
    expect(wrapper.findAll("[data-member-role='root']")).toHaveLength(2);
    expect(wrapper.findAll("[data-member-role='terminal']")).toHaveLength(2);
    expect(wrapper.get("[data-lineage-graph]").attributes("data-node-count")).toBe("4");
    expect(wrapper.get("[data-lineage-graph]").attributes("data-edge-count")).toBe("3");
    expect(wrapper.get("[data-lineage-graph]").attributes("data-read-only")).toBe("true");
  });

  it("creates a repeatable Lineage and deletes an Edge with versioned CSRF requests", async () => {
    let currentVersion = 1;
    const calls: Array<{ url: URL; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://leadtrace.test");
      calls.push({ url, init });
      if (url.pathname === `/api/v2/workspaces/${ids.workspace}`) return response(workspace(currentVersion));
      if (url.pathname.endsWith("/compounds")) return response({ workspace_id: ids.workspace, workspace_version: currentVersion, items: compounds, total: compounds.length });
      if (url.pathname.endsWith("/lineages") && init?.method === "POST") {
        currentVersion += 1;
        const body = JSON.parse(String(init.body));
        return response({ lineage: { ...lineages[1], id: ids.lineages[2], lineage_label: body.lineage_label, sort_order: 2 }, workspace_version: currentVersion }, 201);
      }
      if (url.pathname.endsWith("/lineages")) return response({ workspace_id: ids.workspace, workspace_version: currentVersion, items: lineages, total: lineages.length });
      if (url.pathname === `/api/v2/lineage-edges/${ids.edges[0]}` && init?.method === "DELETE") {
        currentVersion += 1;
        return response({ deleted_id: ids.edges[0], workspace_version: currentVersion });
      }
      throw new Error(`Unexpected request: ${url.pathname}`);
    }));
    const { wrapper } = await mountWorkspace("lineages");

    await wrapper.get("[data-add-lineage]").trigger("click");
    await wrapper.get("[data-lineage-label-input]").setValue("Series C");
    await wrapper.get("[data-save-lineage]").trigger("click");
    await flushPromises();
    await wrapper.get(`[data-edge-id='${edges[0].id}'] [data-delete-edge]`).trigger("click");
    await flushPromises();

    const writes = calls.filter((call) => call.init?.method === "POST" || call.init?.method === "DELETE");
    expect(JSON.parse(String(writes[0]?.init?.body))).toMatchObject({ expected_workspace_version: 1, lineage_label: "Series C" });
    expect(JSON.parse(String(writes[1]?.init?.body))).toEqual({ expected_workspace_version: 2 });
    expect(new Headers(writes[0]?.init?.headers).get("X-CSRF-Token")).toBe("reviewer-csrf");
  });

  it("edits AI-prefilled Lineage metadata and Edge fields in place", async () => {
    let currentVersion = 1;
    const calls: Array<{ url: URL; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://leadtrace.test");
      calls.push({ url, init });
      if (url.pathname === `/api/v2/workspaces/${ids.workspace}`) return response(workspace(currentVersion));
      if (url.pathname.endsWith("/compounds")) return response({ workspace_id: ids.workspace, workspace_version: currentVersion, items: compounds, total: compounds.length });
      if (url.pathname.endsWith("/lineages")) return response({ workspace_id: ids.workspace, workspace_version: currentVersion, items: lineages, total: lineages.length });
      if (url.pathname === `/api/v2/lineages/${ids.lineages[0]}` && init?.method === "PATCH") {
        currentVersion += 1;
        const body = JSON.parse(String(init.body));
        return response({ lineage: { ...lineages[0], lineage_label: body.lineage_label, description: body.description }, workspace_version: currentVersion });
      }
      if (url.pathname === `/api/v2/lineage-edges/${ids.edges[0]}` && init?.method === "PATCH") {
        currentVersion += 1;
        const body = JSON.parse(String(init.body));
        return response({ edge: { ...edges[0], relation_type: body.relation_type, modification_summary: body.modification_summary }, workspace_version: currentVersion });
      }
      throw new Error(`Unexpected request: ${url.pathname}`);
    }));
    const { wrapper } = await mountWorkspace("lineages");

    await wrapper.findAll("[data-lineage-card]")[0]!.get("[data-edit-lineage]").trigger("click");
    await wrapper.get("[data-edit-lineage-label]").setValue("Series A revised");
    await wrapper.get("[data-save-lineage-edit]").trigger("click");
    await flushPromises();
    await wrapper.get(`[data-edge-id='${ids.edges[0]}'] [data-edit-edge]`).trigger("click");
    await wrapper.get("[data-edit-edge-relation]").setValue("bioisostere_replacement");
    await wrapper.get("[data-edit-edge-summary]").setValue("Reviewer corrected transformation");
    await wrapper.get("[data-save-edge-edit]").trigger("click");
    await flushPromises();

    const writes = calls.filter((call) => call.init?.method === "PATCH");
    expect(writes.map((call) => call.url.pathname)).toEqual([
      `/api/v2/lineages/${ids.lineages[0]}`,
      `/api/v2/lineage-edges/${ids.edges[0]}`,
    ]);
    expect(writes.map((call) => JSON.parse(String(call.init?.body)).expected_workspace_version)).toEqual([1, 2]);
    expect(wrapper.text()).toContain("Reviewer corrected transformation");
  });
});

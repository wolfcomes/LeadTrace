import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { activities, compounds, edges, evidence, ids, installReviewer, lineages, links, mountWorkspace, response, workspace } from "./paper-science-v2-fixtures";


describe("Evidence and Activity editor", () => {
  beforeEach(installReviewer);
  afterEach(() => vi.unstubAllGlobals());

  it("shows one Evidence linked to multiple Edges and variable Activity rows", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://leadtrace.test");
      if (url.pathname.endsWith("/lineages")) return response({ workspace_id: ids.workspace, workspace_version: 1, items: lineages, total: lineages.length });
      if (url.pathname.endsWith("/evidence")) return response({ workspace_id: ids.workspace, workspace_version: 1, items: [evidence], total: 1 });
      if (url.pathname.includes("/evidence-links")) {
        const edgeId = url.pathname.split("/")[4];
        const items = links.filter((link) => link.edge_id === edgeId);
        return response({ edge_id: edgeId, workspace_version: 1, items, total: items.length });
      }
      if (url.pathname.endsWith("/compounds")) return response({ workspace_id: ids.workspace, workspace_version: 1, items: compounds, total: compounds.length });
      if (url.pathname.endsWith("/activities")) {
        const compoundId = url.pathname.split("/")[4];
        const items = compoundId === ids.compounds[0] ? activities : [];
        return response({ compound_id: compoundId, workspace_version: 1, items, total: items.length });
      }
      return response(workspace());
    }));

    const { wrapper } = await mountWorkspace("evidence");

    expect(wrapper.findAll("[data-evidence-card]")).toHaveLength(1);
    expect(wrapper.findAll("[data-edge-evidence-link]")).toHaveLength(2);
    expect(wrapper.findAll("[data-activity-row]")).toHaveLength(2);
  });

  it("creates quoted Evidence and links it to multiple Edges sequentially", async () => {
    let currentVersion = 1;
    let nextLink = 0;
    const calls: Array<{ url: URL; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://leadtrace.test");
      calls.push({ url, init });
      if (url.pathname === `/api/v2/workspaces/${ids.workspace}`) return response(workspace(currentVersion));
      if (url.pathname.endsWith("/lineages")) return response({ workspace_id: ids.workspace, workspace_version: currentVersion, items: lineages, total: lineages.length });
      if (url.pathname === `/api/v2/workspaces/${ids.workspace}/evidence` && init?.method === "POST") {
        currentVersion += 1;
        const body = JSON.parse(String(init.body));
        return response({ evidence: { ...evidence, id: ids.evidence[1], page_number: body.page_number, quoted_text: body.quoted_text }, workspace_version: currentVersion }, 201);
      }
      if (url.pathname.endsWith("/evidence") && !init?.method) return response({ workspace_id: ids.workspace, workspace_version: currentVersion, items: [], total: 0 });
      if (url.pathname.endsWith("/evidence-links") && init?.method === "POST") {
        currentVersion += 1;
        const edgeId = url.pathname.split("/")[4];
        const body = JSON.parse(String(init.body));
        const link = { ...links[0], id: ids.links[nextLink], edge_id: edgeId, evidence_id: body.evidence_id, role: body.role };
        nextLink += 1;
        return response({ link, workspace_version: currentVersion }, 201);
      }
      if (url.pathname.endsWith("/evidence-links")) {
        const edgeId = url.pathname.split("/")[4];
        return response({ edge_id: edgeId, workspace_version: currentVersion, items: [], total: 0 });
      }
      if (url.pathname.endsWith("/compounds")) return response({ workspace_id: ids.workspace, workspace_version: currentVersion, items: compounds, total: compounds.length });
      if (url.pathname.endsWith("/activities")) {
        const compoundId = url.pathname.split("/")[4];
        return response({ compound_id: compoundId, workspace_version: currentVersion, items: [], total: 0 });
      }
      throw new Error(`Unexpected request: ${url.pathname}`);
    }));
    const { wrapper } = await mountWorkspace("evidence");

    await wrapper.get("[data-add-evidence]").trigger("click");
    await wrapper.get("[data-evidence-page]").setValue("3");
    await wrapper.get("[data-evidence-quote]").setValue("Optimization evidence");
    const edgeChoices = wrapper.findAll("[data-evidence-edge-choice]");
    await edgeChoices[0]!.setValue(true);
    await edgeChoices[1]!.setValue(true);
    await wrapper.get("[data-save-evidence]").trigger("click");
    await flushPromises();

    const writes = calls.filter((call) => call.init?.method === "POST");
    expect(writes.map((call) => call.url.pathname)).toEqual([
      `/api/v2/workspaces/${ids.workspace}/evidence`,
      `/api/v2/lineage-edges/${ids.edges[0]}/evidence-links`,
      `/api/v2/lineage-edges/${ids.edges[1]}/evidence-links`,
    ]);
    expect(writes.map((call) => JSON.parse(String(call.init?.body)).expected_workspace_version)).toEqual([1, 2, 3]);
  });

  it("opens the Evidence form with a record-addressed Edge preselected", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://leadtrace.test");
      if (url.pathname.endsWith("/lineages")) return response({ workspace_id: ids.workspace, workspace_version: 1, items: lineages, total: lineages.length });
      if (url.pathname.endsWith("/evidence")) return response({ workspace_id: ids.workspace, workspace_version: 1, items: [evidence], total: 1 });
      if (url.pathname.includes("/evidence-links")) {
        const edgeId = url.pathname.split("/")[4];
        return response({ edge_id: edgeId, workspace_version: 1, items: [], total: 0 });
      }
      if (url.pathname.endsWith("/compounds")) return response({ workspace_id: ids.workspace, workspace_version: 1, items: compounds, total: compounds.length });
      if (url.pathname.endsWith("/activities")) {
        const compoundId = url.pathname.split("/")[4];
        return response({ compound_id: compoundId, workspace_version: 1, items: [], total: 0 });
      }
      return response(workspace());
    }));

    const { wrapper } = await mountWorkspace("evidence", ids.edges[1]);

    const edgeChoices = wrapper.findAll<HTMLInputElement>("[data-evidence-edge-choice]");
    expect(edgeChoices).toHaveLength(edges.length);
    expect(edgeChoices[1]!.element.checked).toBe(true);
  });

  it("keeps a created Evidence and retries only a failed Edge link", async () => {
    let currentVersion = 1;
    let secondEdgeAttempts = 0;
    const calls: Array<{ url: URL; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://leadtrace.test");
      calls.push({ url, init });
      if (url.pathname === `/api/v2/workspaces/${ids.workspace}`) return response(workspace(currentVersion));
      if (url.pathname.endsWith("/lineages")) return response({ workspace_id: ids.workspace, workspace_version: currentVersion, items: lineages, total: lineages.length });
      if (url.pathname === `/api/v2/workspaces/${ids.workspace}/evidence` && init?.method === "POST") {
        currentVersion += 1;
        return response({ evidence: { ...evidence, id: ids.evidence[1], quoted_text: "Partial link evidence" }, workspace_version: currentVersion }, 201);
      }
      if (url.pathname.endsWith("/evidence") && !init?.method) return response({ workspace_id: ids.workspace, workspace_version: currentVersion, items: [], total: 0 });
      if (url.pathname.endsWith("/evidence-links") && init?.method === "POST") {
        const edgeId = url.pathname.split("/")[4];
        if (edgeId === ids.edges[1] && secondEdgeAttempts++ === 0) {
          return response({ code: "EVIDENCE_LINK_INVALID", message: "Retry link", request_id: "partial-link", details: {} }, 422);
        }
        currentVersion += 1;
        const body = JSON.parse(String(init.body));
        return response({ link: { ...links[0], id: ids.links[edgeId === ids.edges[0] ? 0 : 1], edge_id: edgeId, evidence_id: body.evidence_id }, workspace_version: currentVersion }, 201);
      }
      if (url.pathname.endsWith("/evidence-links")) {
        const edgeId = url.pathname.split("/")[4];
        return response({ edge_id: edgeId, workspace_version: currentVersion, items: [], total: 0 });
      }
      if (url.pathname.endsWith("/compounds")) return response({ workspace_id: ids.workspace, workspace_version: currentVersion, items: compounds, total: compounds.length });
      if (url.pathname.endsWith("/activities")) {
        const compoundId = url.pathname.split("/")[4];
        return response({ compound_id: compoundId, workspace_version: currentVersion, items: [], total: 0 });
      }
      throw new Error(`Unexpected request: ${url.pathname}`);
    }));
    const { wrapper } = await mountWorkspace("evidence");

    await wrapper.get("[data-add-evidence]").trigger("click");
    await wrapper.get("[data-evidence-page]").setValue("3");
    await wrapper.get("[data-evidence-quote]").setValue("Partial link evidence");
    const edgeChoices = wrapper.findAll("[data-evidence-edge-choice]");
    await edgeChoices[0]!.setValue(true);
    await edgeChoices[1]!.setValue(true);
    await wrapper.get("[data-save-evidence]").trigger("click");
    await flushPromises();

    expect(wrapper.findAll("[data-evidence-card]")).toHaveLength(1);
    expect(wrapper.text()).toContain("部分 Edge 未关联");
    await wrapper.get("[data-save-existing-link]").trigger("click");
    await flushPromises();

    const evidenceCreates = calls.filter((call) => call.url.pathname.endsWith("/evidence") && call.init?.method === "POST");
    expect(evidenceCreates).toHaveLength(1);
    expect(wrapper.findAll("[data-edge-evidence-link]")).toHaveLength(2);
  });

  it("edits AI-prefilled Evidence and Activity records in place", async () => {
    let currentVersion = 1;
    const calls: Array<{ url: URL; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://leadtrace.test");
      calls.push({ url, init });
      if (url.pathname === `/api/v2/workspaces/${ids.workspace}`) return response(workspace(currentVersion));
      if (url.pathname.endsWith("/lineages")) return response({ workspace_id: ids.workspace, workspace_version: currentVersion, items: lineages, total: lineages.length });
      if (url.pathname === `/api/v2/evidence/${ids.evidence[0]}` && init?.method === "PATCH") {
        currentVersion += 1;
        const body = JSON.parse(String(init.body));
        return response({ evidence: { ...evidence, quoted_text: body.quoted_text }, workspace_version: currentVersion });
      }
      if (url.pathname.endsWith("/evidence")) return response({ workspace_id: ids.workspace, workspace_version: currentVersion, items: [evidence], total: 1 });
      if (url.pathname.includes("/evidence-links")) {
        const edgeId = url.pathname.split("/")[4];
        const items = links.filter((link) => link.edge_id === edgeId);
        return response({ edge_id: edgeId, workspace_version: currentVersion, items, total: items.length });
      }
      if (url.pathname.endsWith("/compounds")) return response({ workspace_id: ids.workspace, workspace_version: currentVersion, items: compounds, total: compounds.length });
      if (url.pathname === `/api/v2/activities/${ids.activities[0]}` && init?.method === "PATCH") {
        currentVersion += 1;
        const body = JSON.parse(String(init.body));
        return response({ activity: { ...activities[0], value: body.value }, workspace_version: currentVersion });
      }
      if (url.pathname.endsWith("/activities")) {
        const compoundId = url.pathname.split("/")[4];
        const items = compoundId === ids.compounds[0] ? activities : [];
        return response({ compound_id: compoundId, workspace_version: currentVersion, items, total: items.length });
      }
      throw new Error(`Unexpected request: ${url.pathname}`);
    }));
    const { wrapper } = await mountWorkspace("evidence");

    await wrapper.get("[data-edit-evidence]").trigger("click");
    await wrapper.get("[data-edit-evidence-quote]").setValue("");
    expect(wrapper.get("[data-save-evidence-edit]").attributes("disabled")).toBeDefined();
    await wrapper.get("[data-edit-evidence-quote]").setValue("Reviewer corrected quote");
    expect(wrapper.get("[data-save-evidence-edit]").attributes("disabled")).toBeUndefined();
    await wrapper.get("[data-save-evidence-edit]").trigger("click");
    await flushPromises();
    await wrapper.findAll("[data-activity-row]")[0]!.get("[data-edit-activity]").trigger("click");
    await wrapper.get("[data-edit-activity-value]").setValue("9.5");
    await wrapper.get("[data-save-activity-edit]").trigger("click");
    await flushPromises();

    const writes = calls.filter((call) => call.init?.method === "PATCH");
    expect(writes.map((call) => call.url.pathname)).toEqual([
      `/api/v2/evidence/${ids.evidence[0]}`,
      `/api/v2/activities/${ids.activities[0]}`,
    ]);
    expect(writes.map((call) => JSON.parse(String(call.init?.body)).expected_workspace_version)).toEqual([1, 2]);
    expect(wrapper.text()).toContain("Reviewer corrected quote");
    expect(wrapper.text()).toContain("9.5");
  });
});

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { compounds, ids, installReviewer, mountWorkspace, response, sectionKeys, workspace } from "./paper-science-v2-fixtures";


describe("Reviewer submission checklist", () => {
  beforeEach(installReviewer);
  afterEach(() => vi.unstubAllGlobals());

  it("submits an article problem with a required reason without confirming incomplete content", async () => {
    const calls: Array<{url: string; init?: RequestInit}> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); calls.push({url, init});
      if (url.includes("submission-validation")) return response({valid: false, blockers: [{code: "SECTION_PENDING", message: "Review required", entity_type: "paper_section_review", entity_id: null, section_key: "structures"}]});
      if (url.endsWith("submit-problem")) return response({workspace_version: 2});
      return response(workspace());
    }));
    const {wrapper} = await mountWorkspace("submit");
    expect(wrapper.get("[data-submit-problem]").attributes("disabled")).toBeDefined();
    await wrapper.get("[data-problem-reason]").setValue("  Article has conflicting compound structures  ");
    expect(wrapper.get("[data-submit-problem]").attributes("disabled")).toBeUndefined();
    expect(wrapper.get("[data-submit-paper]").attributes("disabled")).toBeDefined();
    await wrapper.get("[data-submit-problem]").trigger("click");
    await flushPromises();
    const call = calls.find(x => x.url.endsWith("submit-problem"));
    expect(JSON.parse(String(call?.init?.body))).toEqual({expected_workspace_version: 1, reason: "Article has conflicting compound structures"});
    expect(new Headers(call?.init?.headers).get("X-CSRF-Token")).toBe("reviewer-csrf");
    expect(wrapper.text()).toContain("文章问题已提交");
  });

  it("reuses the issue submission idempotency key after a lost response", async () => {
    const keys: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("submission-validation")) return response({valid: false, blockers: []});
      if (url.endsWith("submit-problem")) {
        keys.push(new Headers(init?.headers).get("Idempotency-Key") ?? "");
        if (keys.length === 1) throw new TypeError("Connection closed after write");
        return response({workspace_version: 2});
      }
      return response(workspace());
    }));
    const {wrapper} = await mountWorkspace("submit");
    await wrapper.get("[data-problem-reason]").setValue("Major article problem");
    await wrapper.get("[data-submit-problem]").trigger("click"); await flushPromises();
    await wrapper.get("[data-submit-problem]").trigger("click"); await flushPromises();
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
    expect(wrapper.text()).toContain("文章问题已提交");
  });

  it("renders record-addressable blockers and opens the matching tab and entity", async () => {
    const structureId = "30000000-0000-4000-8000-000000000091";
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://leadtrace.test");
      if (url.pathname.endsWith("/submission-validation")) {
        return response({ valid: false, blockers: [{ code: "STRUCTURE_NOT_CONFIRMED", message: "Confirm Structure", entity_type: "structure", entity_id: structureId, section_key: "structures" }] });
      }
      if (url.pathname.endsWith("/compounds")) return response({ workspace_id: ids.workspace, workspace_version: 1, items: compounds, total: compounds.length });
      if (url.pathname.match(/\/api\/v2\/compounds\/[^/]+\/structure$/)) {
        const compoundId = url.pathname.split("/")[4];
        return response({
          structure: compoundId === ids.compounds[2] ? {
            id: structureId, paper_id: ids.paper, workspace_id: ids.workspace, compound_id: compoundId,
            smiles: "CC", canonical_smiles: "CC", molfile: null, inchi: null, inchikey: null, depiction_asset_id: null,
            status: "draft", input_method: "manual_smiles",
          } : null,
          workspace_version: 1,
        });
      }
      return response(workspace());
    }));
    const { wrapper, router } = await mountWorkspace("submit");

    expect(wrapper.findAll("[data-submission-blocker]")).toHaveLength(1);
    await wrapper.get("[data-submission-blocker]").trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.query).toMatchObject({ tab: "compounds", entity: structureId });
    expect(wrapper.get(`[data-compound-id='${ids.compounds[2]}']`).classes()).toContain("selected");
  });

  it("allows an explicitly not-reported empty section and requires confirmation before submit", async () => {
    const calls: Array<{ url: URL; init?: RequestInit }> = [];
    const current = workspace(1, "completed");
    current.sections = current.sections.map((section) => section.section_key === "activities" ? { ...section, state: "not_reported" } : section);
    const submittedAt = "2026-09-17T04:00:00+00:00";
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://leadtrace.test");
      calls.push({ url, init });
      if (url.pathname.endsWith("/submission-validation")) return response({ valid: true, blockers: [] });
      if (url.pathname.endsWith("/submit") && init?.method === "POST") {
        const sections = current.sections;
        return response({
          submission: {
            id: ids.submission, paper_id: ids.paper, workspace_id: ids.workspace, review_task_id: ids.task, submission_number: 1,
            idempotency_key: `submit-${ids.workspace}-v1`,
            snapshot: {
              schema_version: 1,
              paper: { id: ids.paper, paper_key: "LT-TASK15", title: "Variable lineage paper", journal: "JMC", publication_year: 2024, volume: "67", issue: "5", doi: null, catalog_state: "verified" },
              source: current.source, workspace_version: 2, sections,
              compounds: [], structures: [], structure_source_images: [], lineages: [], lineage_members: [], lineage_edges: [], evidence: [], edge_evidence_links: [], activities: [],
            },
            content_hash: "d".repeat(64), workspace_version: 2, submitted_by_id: ids.reviewer, reviewer_note: "Ready for Admin", submitted_at: submittedAt,
          },
          workspace_version: 2,
        });
      }
      return response(current);
    }));
    const { wrapper } = await mountWorkspace("submit");

    expect(wrapper.findAll("[data-submission-blocker]")).toHaveLength(0);
    expect(wrapper.get("[data-submit-paper]").attributes("disabled")).toBeDefined();
    await wrapper.get("[data-reviewer-note]").setValue("Ready for Admin");
    await wrapper.get("[data-reviewer-confirmation]").setValue(true);
    expect(wrapper.get("[data-submit-paper]").attributes("disabled")).toBeUndefined();
    await wrapper.get("[data-submit-paper]").trigger("click");
    await flushPromises();

    const write = calls.find((call) => call.url.pathname.endsWith("/submit"));
    expect(JSON.parse(String(write?.init?.body))).toEqual({ expected_workspace_version: 1, reviewer_note: "Ready for Admin" });
    expect(new Headers(write?.init?.headers).get("Idempotency-Key")).toBe(`submit-${ids.workspace}-v1`);
    expect(new Headers(write?.init?.headers).get("X-CSRF-Token")).toBe("reviewer-csrf");
    expect(wrapper.text()).toContain("已提交给 Admin 审批");
    expect(sectionKeys).toContain("activities");
  });

  it("opens an undispositioned Edge in the Lineage editor instead of the Evidence form", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://leadtrace.test");
      if (url.pathname.endsWith("/submission-validation")) {
        return response({ valid: false, blockers: [{
          code: "EDGE_NOT_DISPOSITIONED", message: "Disposition Edge", entity_type: "lineage_edge",
          entity_id: ids.edges[0], section_key: "edge_evidence",
        }] });
      }
      return response(workspace());
    }));
    const { wrapper, router } = await mountWorkspace("submit");

    await wrapper.get("[data-submission-blocker]").trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.query).toMatchObject({ tab: "lineages", entity: ids.edges[0] });
  });
});

it('routes a table confirmation blocker to the exact activity comparison table',async()=>{
 installReviewer();const tableId='30000000-0000-4000-8000-000000000080';
 vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>{
  const path=String(input);
  if(path.endsWith('/submission-validation'))return response({valid:false,blockers:[{code:'ACTIVITY_TABLE_NOT_REVIEWED',message:'Confirm Table',entity_type:'activity_table',entity_id:tableId,section_key:'activities'}]});
  if(path.endsWith('/activity-tables'))return response({workspace_id:ids.workspace,workspace_version:1,tables:[{id:tableId,paper_id:ids.paper,workspace_id:ids.workspace,name:'Table 2',kind:'source',source_label:'Table 2',source_title:null,page_number:null,review_hint:null,review_status:'draft',created_by_kind:'ai',columns:[],mode:'any',sort:'label'}],other_activity_ids:[]});
  if(path.endsWith('/activity-comparison'))return response({workspace_id:ids.workspace,workspace_version:1,compounds:[],activities:[]});
  return response(workspace());
 }));
 const {wrapper,router}=await mountWorkspace('submit');await wrapper.get('[data-submission-blocker]').trigger('click');await flushPromises();
 expect(router.currentRoute.value.query).toMatchObject({tab:'activity-comparison',entity:tableId});expect(wrapper.get('[data-table-name]').element).toHaveProperty('value','Table 2');wrapper.unmount();vi.unstubAllGlobals();
});

import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { defineComponent } from "vue";
import { createMemoryHistory } from "vue-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../src/App.vue";
import { createAppRouter } from "../src/app/router";
import { useAuthStore } from "../src/auth/store";


const ids = {
  paper: "10000000-0000-4000-8000-000000000001",
  task: "10000000-0000-4000-8000-000000000002",
  workspace: "10000000-0000-4000-8000-000000000003",
  reviewer: "10000000-0000-4000-8000-000000000004",
  asset: "10000000-0000-4000-8000-000000000005",
  compound: "10000000-0000-4000-8000-000000000006",
  structure: "10000000-0000-4000-8000-000000000007",
  secondCompound: "10000000-0000-4000-8000-000000000008",
  secondStructure: "10000000-0000-4000-8000-000000000009",
};

const sectionKeys = ["bibliography", "compounds", "structures", "lineages", "edge_evidence", "activities"] as const;
function workspace(version = 1) {
  return {
    id: ids.workspace,
    review_task_id: ids.task,
    assigned_reviewer_id: ids.reviewer,
    state: "editing",
    version,
    task_status: "assigned",
    bibliography: { paper_id: ids.paper, paper_key: "LT-JMC-2024-67-05-001", title: "Structure test", journal: "Journal of Medicinal Chemistry", publication_year: 2024, volume: "67", issue: "5", doi: null },
    source: { asset_id: ids.asset, source_root_key: "source_pdfs", source_key: "volume67 issue5/paper-01.pdf", sha256: "a".repeat(64), page_count: 12 },
    sections: sectionKeys.map((section_key) => ({ section_key, state: "pending", note: null })),
  };
}
const compound = { id: ids.compound, paper_id: ids.paper, workspace_id: ids.workspace, compound_label: "7a", display_name: "Lead 7a", description: null, sort_order: 0, created_by_kind: "ai" };
const secondCompound = { ...compound, id: ids.secondCompound, compound_label: "9b", display_name: "Lead 9b", sort_order: 1, created_by_kind: "reviewer" };
function structure(overrides: Record<string, unknown> = {}) {
  return {
    id: ids.structure,
    paper_id: ids.paper,
    workspace_id: ids.workspace,
    compound_id: ids.compound,
    smiles: "CCO",
    molfile: null,
    canonical_smiles: "CCO",
    inchi: "InChI=1S/C2H6O",
    inchikey: "LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
    depiction_asset_id: ids.asset,
    status: "draft",
    input_method: "ai_prefill",
    ...overrides,
  };
}
function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", "X-Request-ID": "structure-ui" } });
}

const KetcherStub = defineComponent({
  name: "KetcherEditor",
  emits: ["update:modelValue"],
  template: `<button data-ketcher-stub type="button" @click="$emit('update:modelValue', 'KETCHER MOLFILE')">Draw molecule</button>`,
});

describe("Compound and single-Structure editor", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    useAuthStore().acceptSession({
      user: { username: "reviewer", display_name: "Reviewer", role: "reviewer", must_change_password: false },
      csrf_token: "reviewer-csrf",
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  function mockApi(initialStructure = structure()) {
    let currentVersion = 1;
    const calls: Array<{ url: URL; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://leadtrace.test");
      calls.push({ url, init });
      if (url.pathname === `/api/v2/workspaces/${ids.workspace}/compounds`) {
        return response({ workspace_id: ids.workspace, workspace_version: currentVersion, items: [compound], total: 1 });
      }
      if (url.pathname === `/api/v2/compounds/${ids.compound}/structure`) {
        if (init?.method === "PUT") {
          currentVersion += 1;
          const body = JSON.parse(String(init.body));
          return response({ structure: structure({ ...body, input_method: body.input_method, status: body.status }), workspace_version: currentVersion });
        }
        return response({ structure: initialStructure, workspace_version: currentVersion });
      }
      if (url.pathname === `/api/v2/compounds/${ids.compound}` && init?.method === "PATCH") {
        currentVersion += 1;
        const body = JSON.parse(String(init.body));
        return response({
          compound: {
            ...compound,
            compound_label: body.compound_label,
            display_name: body.display_name,
            description: body.description,
          },
          workspace_version: currentVersion,
        });
      }
      if (url.pathname === `/api/v2/compounds/${ids.compound}/source-images`) {
        return response({ compound_id: ids.compound, workspace_version: currentVersion, items: [], total: 0 });
      }
      return response(workspace(currentVersion));
    }));
    return calls;
  }

  async function mountWorkspace() {
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/papers/${ids.paper}?workspace=${ids.workspace}&tab=compounds`);
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router], stubs: { KetcherEditor: KetcherStub } } });
    await flushPromises();
    return wrapper;
  }

  it("edits one AI-prefilled Structure in place without candidates or confidence", async () => {
    const calls = mockApi();
    const wrapper = await mountWorkspace();

    expect(wrapper.findAll("[data-compound-row]")).toHaveLength(1);
    expect(wrapper.findAll("[data-structure-editor]")).toHaveLength(1);
    expect(wrapper.get("[data-structure-input-method]").text()).toContain("AI 预填");
    expect((wrapper.get("[data-smiles-input]").element as HTMLTextAreaElement).value).toBe("CCO");
    expect(wrapper.text()).not.toContain("置信度");
    expect(wrapper.text()).not.toContain("候选结构");

    await wrapper.get("[data-smiles-input]").setValue("CCN");
    expect(wrapper.get("[data-confirm-structure]").attributes("disabled")).toBeDefined();
    await wrapper.get("[data-save-structure]").trigger("click");
    await flushPromises();

    const writes = calls.filter((call) => call.init?.method === "PUT");
    expect(writes).toHaveLength(1);
    expect(writes[0]?.url.pathname).toBe(`/api/v2/compounds/${ids.compound}/structure`);
    expect(JSON.parse(String(writes[0]?.init?.body))).toEqual({
      expected_workspace_version: 1,
      status: "draft",
      input_method: "manual_smiles",
      smiles: "CCN",
      molfile: null,
    });
  });

  it("sends Ketcher Molfile through the same single-Structure PUT endpoint", async () => {
    const calls = mockApi();
    const wrapper = await mountWorkspace();

    await wrapper.get("[data-open-ketcher]").trigger("click");
    expect(wrapper.get("[data-save-ketcher]").attributes("disabled")).toBeDefined();
    await wrapper.get("[data-ketcher-stub]").trigger("click");
    expect(wrapper.get("[data-save-ketcher]").attributes("disabled")).toBeUndefined();
    await wrapper.get("[data-save-ketcher]").trigger("click");
    await flushPromises();

    const write = calls.find((call) => call.init?.method === "PUT");
    expect(write?.url.pathname).toBe(`/api/v2/compounds/${ids.compound}/structure`);
    expect(JSON.parse(String(write?.init?.body))).toMatchObject({
      expected_workspace_version: 1,
      status: "draft",
      input_method: "structure_editor",
      smiles: null,
      molfile: "KETCHER MOLFILE",
    });
  });

  it("edits AI-prefilled Compound metadata in place", async () => {
    const calls = mockApi();
    const wrapper = await mountWorkspace();

    await wrapper.get("[data-edit-compound]").trigger("click");
    await wrapper.get("[data-edit-compound-label]").setValue("7b");
    await wrapper.get("[data-edit-compound-name]").setValue("Reviewed lead");
    await wrapper.get("[data-save-compound]").trigger("click");
    await flushPromises();

    const write = calls.find((call) => call.url.pathname === `/api/v2/compounds/${ids.compound}`);
    expect(write?.init?.method).toBe("PATCH");
    expect(JSON.parse(String(write?.init?.body))).toEqual({
      expected_workspace_version: 1,
      compound_label: "7b",
      display_name: "Reviewed lead",
      description: null,
    });
    expect(new Headers(write?.init?.headers).get("X-CSRF-Token")).toBe("reviewer-csrf");
    expect(wrapper.get("[data-structure-editor] h3").text()).toContain("7b");
  });

  it("keeps an invalid Draft editable and prevents confirmation", async () => {
    mockApi(structure({ smiles: "not a molecule", canonical_smiles: null, inchi: null, inchikey: null, depiction_asset_id: null }));
    const wrapper = await mountWorkspace();

    expect(wrapper.get("[data-structure-status]").text()).toContain("Draft");
    expect(wrapper.get("[data-smiles-input]").attributes("disabled")).toBeUndefined();
    expect(wrapper.get("[data-confirm-structure]").attributes("disabled")).toBeDefined();
    expect(wrapper.get("[data-structure-guidance]").text()).toContain("先保存 Draft");
    expect(wrapper.text()).not.toContain("修改历史");
  });

  it("marks a Compound Structure as not reported without creating a placeholder", async () => {
    const calls = mockApi();
    const wrapper = await mountWorkspace();

    await wrapper.get("[data-mark-structure='not_reported']").trigger("click");
    await flushPromises();

    const write = calls.find((call) => call.init?.method === "PUT");
    expect(JSON.parse(String(write?.init?.body))).toEqual({
      expected_workspace_version: 1,
      status: "not_reported",
      input_method: "manual_smiles",
      smiles: null,
      molfile: null,
    });
  });

  it("keeps the selected Compound when an older Structure read finishes late", async () => {
    let finishFirstRead: ((value: Response) => void) | undefined;
    const firstRead = new Promise<Response>((resolve) => { finishFirstRead = resolve; });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://leadtrace.test");
      if (url.pathname === `/api/v2/workspaces/${ids.workspace}/compounds`) {
        return response({ workspace_id: ids.workspace, workspace_version: 1, items: [compound, secondCompound], total: 2 });
      }
      if (url.pathname === `/api/v2/compounds/${ids.compound}/structure`) return firstRead;
      if (url.pathname === `/api/v2/compounds/${ids.secondCompound}/structure`) {
        return response({
          structure: structure({ id: ids.secondStructure, compound_id: ids.secondCompound, smiles: "CCN", canonical_smiles: "CCN" }),
          workspace_version: 1,
        });
      }
      if (url.pathname.endsWith("/source-images")) {
        return response({ compound_id: ids.secondCompound, workspace_version: 1, items: [], total: 0 });
      }
      return response(workspace());
    }));
    const wrapper = await mountWorkspace();

    await wrapper.findAll("[data-compound-row]")[1]!.get("button").trigger("click");
    await flushPromises();
    expect(wrapper.get("[data-structure-editor] h3").text()).toContain("9b");
    expect((wrapper.get("[data-smiles-input]").element as HTMLTextAreaElement).value).toBe("CCN");

    finishFirstRead?.(response({ structure: structure(), workspace_version: 1 }));
    await flushPromises();

    expect(wrapper.get("[data-structure-editor] h3").text()).toContain("9b");
    expect((wrapper.get("[data-smiles-input]").element as HTMLTextAreaElement).value).toBe("CCN");
  });

  it("does not show an earlier Compound mutation error after selection changes", async () => {
    let rejectFirstSave: ((reason: Response) => void) | undefined;
    const firstSave = new Promise<Response>((resolve) => { rejectFirstSave = resolve; });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://leadtrace.test");
      if (url.pathname === `/api/v2/workspaces/${ids.workspace}/compounds`) {
        return response({ workspace_id: ids.workspace, workspace_version: 1, items: [compound, secondCompound], total: 2 });
      }
      if (url.pathname === `/api/v2/compounds/${ids.compound}/structure`) {
        if (init?.method === "PUT") return firstSave;
        return response({ structure: structure(), workspace_version: 1 });
      }
      if (url.pathname === `/api/v2/compounds/${ids.secondCompound}/structure`) {
        return response({
          structure: structure({ id: ids.secondStructure, compound_id: ids.secondCompound, smiles: "CCN", canonical_smiles: "CCN" }),
          workspace_version: 1,
        });
      }
      if (url.pathname.endsWith("/source-images")) {
        return response({ compound_id: ids.secondCompound, workspace_version: 1, items: [], total: 0 });
      }
      return response(workspace());
    }));
    const wrapper = await mountWorkspace();

    await wrapper.get("[data-smiles-input]").setValue("invalid draft");
    void wrapper.get("[data-save-structure]").trigger("click");
    await flushPromises();
    await wrapper.findAll("[data-compound-row]")[1]!.get("button").trigger("click");
    await flushPromises();
    rejectFirstSave?.(response({
      code: "STRUCTURE_INVALID",
      message: "Invalid structure",
      request_id: "late-error",
    }, 422));
    await flushPromises();

    expect(wrapper.get("[data-structure-editor] h3").text()).toContain("9b");
    expect((wrapper.get("[data-smiles-input]").element as HTMLTextAreaElement).value).toBe("CCN");
    expect(wrapper.text()).not.toContain("该结构无法被 RDKit");
  });

  it("reloads the Workspace after a nested Structure version conflict before retrying", async () => {
    let workspaceReads = 0;
    let structureReads = 0;
    let writes = 0;
    const writeBodies: Array<Record<string, unknown>> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://leadtrace.test");
      if (url.pathname === `/api/v2/workspaces/${ids.workspace}`) {
        workspaceReads += 1;
        return response(workspace(workspaceReads === 1 ? 1 : 2));
      }
      if (url.pathname === `/api/v2/workspaces/${ids.workspace}/compounds`) {
        return response({ workspace_id: ids.workspace, workspace_version: 1, items: [compound], total: 1 });
      }
      if (url.pathname === `/api/v2/compounds/${ids.compound}/structure`) {
        if (init?.method === "PUT") {
          writes += 1;
          const body = JSON.parse(String(init.body));
          writeBodies.push(body);
          if (writes === 1) {
            return response({
              code: "WORKSPACE_VERSION_CONFLICT",
              message: "Workspace version changed",
              request_id: "nested-conflict",
              details: { expected_workspace_version: 1, current_workspace_version: 2 },
            }, 409);
          }
          return response({ structure: structure({ smiles: body.smiles, input_method: body.input_method }), workspace_version: 3 });
        }
        structureReads += 1;
        return response({ structure: structure(), workspace_version: structureReads === 1 ? 1 : 2 });
      }
      if (url.pathname.endsWith("/source-images")) {
        return response({ compound_id: ids.compound, workspace_version: 1, items: [], total: 0 });
      }
      throw new Error(`Unexpected request: ${url.pathname}`);
    }));
    const wrapper = await mountWorkspace();

    await wrapper.get("[data-smiles-input]").setValue("CCN");
    await wrapper.get("[data-save-structure]").trigger("click");
    await flushPromises();

    expect(workspaceReads).toBe(2);
    expect(structureReads).toBe(2);
    expect(wrapper.get("[data-concurrency-alert]").text()).toContain("已重新载入最新版本");
    expect(wrapper.get("[data-workspace-version]").text()).toContain("v2");

    await wrapper.get("[data-save-structure]").trigger("click");
    await flushPromises();
    expect(writeBodies.map((body) => body.expected_workspace_version)).toEqual([1, 2]);
  });
});

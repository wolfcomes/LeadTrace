import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory } from "vue-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../src/App.vue";
import type { StructureSourceImage } from "../src/v2/types";
import { createAppRouter } from "../src/app/router";
import { useAuthStore } from "../src/auth/store";


vi.mock('pdfjs-dist',()=>({GlobalWorkerOptions:{},getDocument:()=>({destroy:()=>Promise.resolve(),promise:Promise.resolve({getPage:()=>Promise.resolve({getViewport:()=>({width:800,height:600}),render:()=>({promise:Promise.resolve(),cancel:()=>{}})})})})}));
const ids = {
  paper: "20000000-0000-4000-8000-000000000001", task: "20000000-0000-4000-8000-000000000002",
  workspace: "20000000-0000-4000-8000-000000000003", reviewer: "20000000-0000-4000-8000-000000000004",
  asset: "20000000-0000-4000-8000-000000000005", compound: "20000000-0000-4000-8000-000000000006",
  structure: "20000000-0000-4000-8000-000000000007", readyImage: "20000000-0000-4000-8000-000000000008",
  failedImage: "20000000-0000-4000-8000-000000000009",
  secondCompound: "20000000-0000-4000-8000-000000000010",
  secondStructure: "20000000-0000-4000-8000-000000000011",
  secondImage: "20000000-0000-4000-8000-000000000012",
};
const sectionKeys = ["bibliography", "compounds", "structures", "lineages", "edge_evidence", "activities"] as const;
function workspace(version = 1) { return { id: ids.workspace, review_task_id: ids.task, assigned_reviewer_id: ids.reviewer, state: "editing", version, task_status: "assigned", bibliography: { paper_id: ids.paper, paper_key: "LT-JMC-2024-67-05-002", title: "Source image test", journal: "Journal of Medicinal Chemistry", publication_year: 2024, volume: "67", issue: "5", doi: null }, source: { asset_id: ids.asset, source_root_key: "source_pdfs", source_key: "volume67 issue5/paper-02.pdf", sha256: "b".repeat(64), page_count: 12 }, sections: sectionKeys.map((section_key) => ({ section_key, state: "pending", note: null })) }; }
const compound = { id: ids.compound, paper_id: ids.paper, workspace_id: ids.workspace, compound_label: "12", display_name: null, description: null, sort_order: 0, created_by_kind: "reviewer" };
const secondCompound = { ...compound, id: ids.secondCompound, compound_label: "13", sort_order: 1 };
const structure = { id: ids.structure, paper_id: ids.paper, workspace_id: ids.workspace, compound_id: ids.compound, smiles: "CCO", molfile: null, canonical_smiles: "CCO", inchi: "InChI=1S/C2H6O", inchikey: "LFQSCWFLJHTTHZ-UHFFFAOYSA-N", depiction_asset_id: ids.asset, status: "draft", input_method: "manual_smiles" };
function sourceImage(id: string, cropStatus: "ready" | "failed", compoundId = ids.compound, pageNumber = 2): StructureSourceImage { return { id, paper_id: ids.paper, workspace_id: ids.workspace, compound_id: compoundId, source_sha256: "b".repeat(64), page_number: pageNumber, bbox: { x0: 0.1, y0: 0.2, x1: 0.4, y1: 0.6 }, source_context: null, label: "Scheme 1", reviewer_note: null, crop_status: cropStatus, crop_asset_id: cropStatus === "ready" ? ids.asset : null }; }
function response(body: unknown, status = 200): Response { return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", "X-Request-ID": "source-image-ui" } }); }

describe("Structure Source Images", () => {
  beforeEach(() => {
    vi.spyOn(HTMLCanvasElement.prototype,"getContext").mockReturnValue({drawImage:vi.fn()} as any);
    setActivePinia(createPinia());
    useAuthStore().acceptSession({ user: { username: "reviewer", display_name: "Reviewer", role: "reviewer", must_change_password: false }, csrf_token: "reviewer-csrf" });
  });
  afterEach(() => {vi.unstubAllGlobals();vi.restoreAllMocks();});

  function mockApi(images: ReturnType<typeof sourceImage>[] = []) {
    let currentVersion = 1;
    const calls: Array<{ url: URL; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://leadtrace.test");
      calls.push({ url, init });
      if (url.pathname === `/api/v2/workspaces/${ids.workspace}/compounds`) return response({ workspace_id: ids.workspace, workspace_version: currentVersion, items: [compound], total: 1 });
      if (url.pathname === `/api/v2/compounds/${ids.compound}/structure`) return response({ structure, workspace_version: currentVersion });
      if (url.pathname === `/api/v2/compounds/${ids.compound}/source-images`) {
        if (init?.method === "POST") {
          currentVersion += 1;
          return response({ source_image: sourceImage(ids.readyImage, "ready"), workspace_version: currentVersion }, 201);
        }
        return response({ compound_id: ids.compound, workspace_version: currentVersion, items: images, total: images.length });
      }
      if (url.pathname === `/api/v2/structure-source-images/${ids.failedImage}/retry`) {
        currentVersion += 1;
        return response({ source_image: sourceImage(ids.failedImage, "ready"), workspace_version: currentVersion });
      }
      return response(workspace(currentVersion));
    }));
    return calls;
  }

  async function mountWorkspace() {
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/papers/${ids.paper}?workspace=${ids.workspace}&tab=compounds`);
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();
    return wrapper;
  }

  it("uses an explicit PDF rectangle-selection mode and submits normalized coordinates", async () => {
    const calls = mockApi();
    const wrapper = await mountWorkspace();

    expect(wrapper.find("[data-pdf-page]").exists()).toBe(false);
    await wrapper.get("[data-capture-source-image]").trigger("click");
    await flushPromises();
    expect(wrapper.get("[data-pdf-page]").attributes("data-selection-mode")).toBe("true");
    expect(wrapper.get('button[aria-label="旋转"]').attributes("disabled")).toBeDefined();

    const page = wrapper.get("[data-pdf-page]");
    const pageRect: DOMRect = {
      x: 37.25,
      y: 49.75,
      left: 37.25,
      top: 49.75,
      width: 812.75,
      height: 527.125,
      right: 850,
      bottom: 576.875,
      toJSON: () => ({}),
    };
    vi.spyOn(page.element, "getBoundingClientRect").mockReturnValue(pageRect);
    const rawBounds = {
      x0: 0.15683718909525357,
      y0: 0.22703818369453047,
      x1: 0.6357481626298831,
      y1: 0.7391812865497076,
    };
    await page.trigger("pointerdown", {
      pointerId: 1,
      clientX: pageRect.left + pageRect.width * rawBounds.x0,
      clientY: pageRect.top + pageRect.height * rawBounds.y0,
    });
    await page.trigger("pointermove", {
      pointerId: 1,
      clientX: pageRect.left + pageRect.width * rawBounds.x1,
      clientY: pageRect.top + pageRect.height * rawBounds.y1,
    });
    await page.trigger("pointerup", {
      pointerId: 1,
      clientX: pageRect.left + pageRect.width * rawBounds.x1,
      clientY: pageRect.top + pageRect.height * rawBounds.y1,
    });
    await flushPromises();

    const create = calls.find((call) => call.url.pathname.endsWith("/source-images") && call.init?.method === "POST");
    expect(JSON.parse(String(create?.init?.body))).toEqual({
      expected_workspace_version: 1,
      source_sha256: "b".repeat(64),
      page_number: 1,
      bbox: { x0: 0.1568371891, y0: 0.2270381837, x1: 0.6357481626, y1: 0.7391812865 },
      source_context: null,
      label: null,
      reviewer_note: null,
    });
  });

  it("shows Source crops beside the RDKit depiction and retries failed crops", async () => {
    const calls = mockApi([sourceImage(ids.readyImage, "ready"), sourceImage(ids.failedImage, "failed")]);
    const wrapper = await mountWorkspace();

    const imageSources = wrapper.findAll("[data-structure-comparison] img").map((image) => image.attributes("src"));
    expect(imageSources).toContain(`/api/v2/compounds/${ids.compound}/structure/depiction?v=${ids.asset}`);
    expect(imageSources).toContain(`/api/v2/structure-source-images/${ids.readyImage}/content`);
    expect(wrapper.get(`[data-source-image-id='${ids.failedImage}']`).text()).toContain("生成失败");

    await wrapper.get(`[data-source-image-id='${ids.failedImage}'] [data-retry-crop]`).trigger("click");
    await flushPromises();
    const retry = calls.find((call) => call.url.pathname.endsWith(`/${ids.failedImage}/retry`));
    expect(retry?.init?.method).toBe("POST");
    expect(JSON.parse(String(retry?.init?.body))).toEqual({ expected_workspace_version: 1 });
    expect(new Headers(retry?.init?.headers).get("X-CSRF-Token")).toBe("reviewer-csrf");
  });

  it("explains shared source scaffolds and offers the original crop at full size", async () => {
    const image = { ...sourceImage(ids.readyImage, "ready"), source_context: "共享骨架与编号行；不是独立完整结构。" };
    mockApi([image]);
    const wrapper = await mountWorkspace();
    const card = wrapper.get(`[data-source-image-id='${ids.readyImage}']`);
    expect(card.text()).toContain(image.source_context);
    expect(card.get("a[data-open-source-crop]").attributes("href")).toBe(`/api/v2/structure-source-images/${ids.readyImage}/content`);
    expect(card.get("a[data-open-source-crop]").attributes("target")).toBe("_blank");
  });

  it("does not replace the selected Compound's Source Images with a late older read", async () => {
    let finishFirstImages: ((value: Response) => void) | undefined;
    const firstImages = new Promise<Response>((resolve) => { finishFirstImages = resolve; });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://leadtrace.test");
      if (url.pathname === `/api/v2/workspaces/${ids.workspace}/compounds`) {
        return response({ workspace_id: ids.workspace, workspace_version: 1, items: [compound, secondCompound], total: 2 });
      }
      if (url.pathname === `/api/v2/compounds/${ids.compound}/structure`) {
        return response({ structure, workspace_version: 1 });
      }
      if (url.pathname === `/api/v2/compounds/${ids.secondCompound}/structure`) {
        return response({ structure: { ...structure, id: ids.secondStructure, compound_id: ids.secondCompound }, workspace_version: 1 });
      }
      if (url.pathname === `/api/v2/compounds/${ids.compound}/source-images`) return firstImages;
      if (url.pathname === `/api/v2/compounds/${ids.secondCompound}/source-images`) {
        const image = sourceImage(ids.secondImage, "ready", ids.secondCompound, 5);
        return response({ compound_id: ids.secondCompound, workspace_version: 1, items: [image], total: 1 });
      }
      return response(workspace());
    }));
    const wrapper = await mountWorkspace();

    await wrapper.findAll("[data-compound-row]")[1]!.get("button").trigger("click");
    await flushPromises();
    expect(wrapper.get(`[data-source-image-id='${ids.secondImage}']`).text()).toContain("p5");

    const oldImage = sourceImage(ids.readyImage, "ready");
    finishFirstImages?.(response({ compound_id: ids.compound, workspace_version: 1, items: [oldImage], total: 1 }));
    await flushPromises();

    expect(wrapper.find(`[data-source-image-id='${ids.readyImage}']`).exists()).toBe(false);
    expect(wrapper.get(`[data-source-image-id='${ids.secondImage}']`).text()).toContain("p5");
  });

  it("reloads sibling Structure data after a Source Image version conflict", async () => {
    let workspaceReads = 0;
    let structureReads = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://leadtrace.test");
      if (url.pathname === `/api/v2/workspaces/${ids.workspace}`) {
        workspaceReads += 1;
        return response(workspace(workspaceReads === 1 ? 1 : 2));
      }
      if (url.pathname === `/api/v2/workspaces/${ids.workspace}/compounds`) {
        return response({ workspace_id: ids.workspace, workspace_version: workspaceReads === 1 ? 1 : 2, items: [compound], total: 1 });
      }
      if (url.pathname === `/api/v2/compounds/${ids.compound}/structure`) {
        structureReads += 1;
        return response({
          structure: { ...structure, smiles: structureReads === 1 ? "CCO" : "CCN", canonical_smiles: structureReads === 1 ? "CCO" : "CCN" },
          workspace_version: structureReads === 1 ? 1 : 2,
        });
      }
      if (url.pathname === `/api/v2/compounds/${ids.compound}/source-images`) {
        const image = sourceImage(ids.failedImage, "failed");
        return response({ compound_id: ids.compound, workspace_version: workspaceReads === 1 ? 1 : 2, items: [image], total: 1 });
      }
      if (url.pathname === `/api/v2/structure-source-images/${ids.failedImage}/retry` && init?.method === "POST") {
        return response({
          code: "WORKSPACE_VERSION_CONFLICT",
          message: "Workspace version changed",
          request_id: "source-image-conflict",
          details: { expected_workspace_version: 1, current_workspace_version: 2 },
        }, 409);
      }
      throw new Error(`Unexpected request: ${url.pathname}`);
    }));
    const wrapper = await mountWorkspace();
    expect((wrapper.get("[data-smiles-input]").element as HTMLTextAreaElement).value).toBe("CCO");

    await wrapper.get(`[data-source-image-id='${ids.failedImage}'] [data-retry-crop]`).trigger("click");
    await flushPromises();

    expect(workspaceReads).toBe(2);
    // An open detail may also refresh while the conflict recovery remounts it.
    expect(structureReads).toBeGreaterThanOrEqual(2);
    expect((wrapper.get("[data-smiles-input]").element as HTMLTextAreaElement).value).toBe("CCN");
  });
});

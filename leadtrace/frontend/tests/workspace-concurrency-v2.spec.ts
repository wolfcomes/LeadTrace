import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";

import App from "../src/App.vue";
import { createAppRouter } from "../src/app/router";
import { useAuthStore } from "../src/auth/store";
import type { PaperWorkspace } from "../src/v2/types";


const ids = {
  paper: "10000000-0000-4000-8000-000000000001",
  task: "10000000-0000-4000-8000-000000000002",
  workspace: "10000000-0000-4000-8000-000000000003",
  reviewer: "10000000-0000-4000-8000-000000000004",
  asset: "10000000-0000-4000-8000-000000000005",
};
const sectionKeys = ["bibliography", "compounds", "structures", "lineages", "edge_evidence", "activities"] as const;
function workspace(version = 1): PaperWorkspace {
  return {
    id: ids.workspace,
    review_task_id: ids.task,
    assigned_reviewer_id: ids.reviewer,
    state: "editing",
    version,
    task_status: "assigned",
    bibliography: { paper_id: ids.paper, paper_key: "LT-JMC-2024-67-05-001", title: "Blank reviewer workspace", journal: "Journal of Medicinal Chemistry", publication_year: 2024, volume: "67", issue: "5", doi: null },
    source: { asset_id: ids.asset, source_root_key: "source_pdfs", source_key: "volume67 issue5/paper-01.pdf", sha256: "a".repeat(64), page_count: 12 },
    sections: sectionKeys.map((section_key) => ({ section_key, state: "pending", note: null })),
  };
}
function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", "X-Request-ID": "workspace-v2-ui" } });
}


describe("paper Workspace concurrency", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    useAuthStore().acceptSession({
      user: { username: "reviewer", display_name: "核查员", role: "reviewer", must_change_password: false },
      csrf_token: "reviewer-csrf",
    });
  });

  afterEach(() => vi.unstubAllGlobals());

  it("reloads the authoritative aggregate after 409 and never retries the stale mutation", async () => {
    const calls: Array<{ url: URL; init?: RequestInit }> = [];
    let reads = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://leadtrace.test");
      calls.push({ url, init });
      if (init?.method === "PUT") {
        return response({
          code: "WORKSPACE_VERSION_CONFLICT",
          message: "Workspace version changed",
          request_id: "conflict-request",
          details: { expected_workspace_version: 1, current_workspace_version: 2 },
        }, 409);
      }
      reads += 1;
      const latest = workspace(2);
      latest.sections[1] = { section_key: "compounds", state: "completed", note: "Other session" };
      return response(reads === 1 ? workspace(1) : latest);
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/papers/${ids.paper}?workspace=${ids.workspace}`);
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    await wrapper.get("[data-section-key='compounds'] [data-section-choice='completed']").trigger("click");
    await flushPromises();

    const writes = calls.filter((call) => call.init?.method === "PUT");
    expect(writes).toHaveLength(1);
    expect(JSON.parse(String(writes[0]?.init?.body))).toEqual({
      expected_workspace_version: 1,
      state: "completed",
      note: null,
    });
    expect(new Headers(writes[0]?.init?.headers).get("X-CSRF-Token")).toBe("reviewer-csrf");
    expect(calls.filter((call) => call.init?.method !== "PUT")).toHaveLength(2);
    expect(wrapper.get("[data-concurrency-alert]").text()).toContain("已重新载入最新版本");
    expect(wrapper.get("[data-workspace-version]").text()).toContain("v2");
    expect(wrapper.get("[data-section-key='compounds']").attributes("data-state")).toBe("completed");
  });

  it("invalidates and reloads the aggregate after a successful mutation", async () => {
    const calls: Array<{ url: URL; init?: RequestInit }> = [];
    let reads = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://leadtrace.test");
      calls.push({ url, init });
      if (init?.method === "PUT") return response(workspace(2));
      reads += 1;
      return response(reads === 1 ? workspace(1) : workspace(2));
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/papers/${ids.paper}?workspace=${ids.workspace}`);
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    await wrapper.get("[data-section-key='bibliography'] [data-section-choice='completed']").trigger("click");
    await flushPromises();

    expect(calls.filter((call) => call.init?.method === "PUT")).toHaveLength(1);
    expect(calls.filter((call) => call.init?.method !== "PUT")).toHaveLength(2);
    expect(wrapper.get("[data-workspace-version]").text()).toContain("v2");
  });

  it("does not let an in-flight mutation reload replace a newer Workspace navigation", async () => {
    const secondWorkspaceId = "10000000-0000-4000-8000-000000000006";
    const calls: Array<{ url: URL; init?: RequestInit }> = [];
    let finishMutation: ((response: Response) => void) | undefined;
    const pendingMutation = new Promise<Response>((resolve) => {
      finishMutation = resolve;
    });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://leadtrace.test");
      calls.push({ url, init });
      if (init?.method === "PUT") return pendingMutation;
      const result = workspace(url.pathname.endsWith(secondWorkspaceId) ? 7 : 1);
      if (url.pathname.endsWith(secondWorkspaceId)) {
        result.id = secondWorkspaceId;
        result.bibliography.title = "Reassigned Workspace";
      }
      return response(result);
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/papers/${ids.paper}?workspace=${ids.workspace}`);
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    const mutation = wrapper.get("[data-section-key='compounds'] [data-section-choice='completed']").trigger("click");
    await flushPromises();
    await router.replace({ path: `/review/papers/${ids.paper}`, query: { workspace: secondWorkspaceId } });
    await flushPromises();
    finishMutation?.(response(workspace(2)));
    await mutation;
    await flushPromises();

    expect(calls.filter((call) => call.init?.method !== "PUT").map((call) => call.url.pathname)).toEqual([
      `/api/v2/workspaces/${ids.workspace}`,
      `/api/v2/workspaces/${secondWorkspaceId}`,
    ]);
    expect(wrapper.get("h1").text()).toBe("Reassigned Workspace");
    expect(wrapper.get("[data-workspace-version]").text()).toContain("v7");
  });
});

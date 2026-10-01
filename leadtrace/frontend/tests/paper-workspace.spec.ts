import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";

import App from "../src/App.vue";
import { createAppRouter } from "../src/app/router";
import { useAuthStore } from "../src/auth/store";


export const ids = {
  paper: "10000000-0000-4000-8000-000000000001",
  task: "10000000-0000-4000-8000-000000000002",
  workspace: "10000000-0000-4000-8000-000000000003",
  reviewer: "10000000-0000-4000-8000-000000000004",
  asset: "10000000-0000-4000-8000-000000000005",
};

export const sectionKeys = [
  "bibliography",
  "compounds",
  "structures",
  "lineages",
  "edge_evidence",
  "activities",
] as const;

export function workspace(version = 1) {
  return {
    id: ids.workspace,
    review_task_id: ids.task,
    assigned_reviewer_id: ids.reviewer,
    state: "editing",
    version,
    task_status: "assigned",
    bibliography: {
      paper_id: ids.paper,
      paper_key: "LT-JMC-2024-67-05-001",
      title: "Blank reviewer workspace",
      journal: "Journal of Medicinal Chemistry",
      publication_year: 2024,
      volume: "67",
      issue: "5",
      doi: "10.1021/acs.jmedchem.4c00001",
    },
    source: {
      asset_id: ids.asset,
      source_root_key: "source_pdfs",
      source_key: "volume67 issue5/paper-01.pdf",
      sha256: "a".repeat(64),
      page_count: 12,
    },
    sections: sectionKeys.map((section_key) => ({ section_key, state: "pending", note: null })),
  };
}

export const taskList = {
  items: [{
    review_task_id: ids.task,
    workspace_id: ids.workspace,
    paper_id: ids.paper,
    paper_key: "LT-JMC-2024-67-05-001",
    title: "Blank reviewer workspace",
    task_status: "assigned",
    task_version: 1,
    workspace_state: "editing",
    workspace_version: 1,
  }],
  total: 1,
};

export function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "X-Request-ID": "workspace-v2-ui" },
  });
}

describe("paper-centric Reviewer workspace", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    useAuthStore().acceptSession({
      user: { username: "reviewer", display_name: "核查员", role: "reviewer", must_change_password: false },
      csrf_token: "reviewer-csrf",
    });
  });

  afterEach(() => vi.unstubAllGlobals());

  it("lists only paper-centric tasks and opens the assigned Paper workspace", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response(taskList)));
    const router = createAppRouter(createMemoryHistory());
    await router.push("/review/tasks");
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.get("h1").text()).toBe("我的任务");
    expect(wrapper.get("[data-review-task]").text()).toContain("Blank reviewer workspace");
    expect(wrapper.get("[data-open-workspace]").attributes("href")).toBe(
      `/review/papers/${ids.paper}?workspace=${ids.workspace}`,
    );
    expect(wrapper.text()).not.toContain("Changeset");
    expect(wrapper.text()).not.toContain("分子对象");
  });

  it("opens a blank assignment with four tabs, six pending decisions, and add controls", async () => {
    const requests: URL[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://leadtrace.test");
      if (url.pathname.endsWith("/review-progress")) return response({},404);
      // Supporting lists are tested in their own components; count aggregate navigation here.
      if (['/compound-highlights','/evidence','/compounds'].some(x=>url.pathname.endsWith(x))) return response({workspace_id:ids.workspace,workspace_version:1,items:[],total:0});
      requests.push(url);
      if (url.pathname.endsWith("/compounds")) {
        return response({ workspace_id: ids.workspace, workspace_version: 1, items: [], total: 0 });
      }
      return response(workspace());
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/papers/${ids.paper}?workspace=${ids.workspace}&tab=compounds&page=3&entity=draft-1&filter=pending`);
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    expect(requests.map((url) => url.pathname)).toEqual([
      `/api/v2/workspaces/${ids.workspace}`,
    ]);
    expect(wrapper.get("[data-paper-workspace]").classes()).toContain("paper-workspace-shell");
    expect(wrapper.findAll("[data-workspace-tab]")).toHaveLength(4);
    expect(wrapper.findAll("[data-section-status]")).toHaveLength(6);
    expect(wrapper.findAll("[data-section-status][data-state='pending']")).toHaveLength(6);
    expect(wrapper.get("[data-add-compound]").attributes("disabled")).toBeUndefined();
    expect(wrapper.get("[data-source-pdf]").attributes("href")).toBe(`/api/v2/papers/${ids.paper}/source-pdf`);
    expect(wrapper.text()).not.toContain("baseline");
    expect(wrapper.text()).not.toContain("Release");

    await wrapper.findAll("[data-workspace-tab]")[2]?.trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.query).toMatchObject({
      workspace: ids.workspace,
      tab: "lineages",
      page: "3",
      entity: "draft-1",
      filter: "pending",
    });
  });

  it("resolves a direct Paper URL through the Review Task list when workspace is absent", async () => {
    const requests: URL[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://leadtrace.test");
      if (url.pathname.endsWith("/review-progress")) return response({},404);
      // Supporting lists are tested in their own components; count aggregate navigation here.
      if (['/compound-highlights','/evidence','/compounds'].some(x=>url.pathname.endsWith(x))) return response({workspace_id:ids.workspace,workspace_version:1,items:[],total:0});
      requests.push(url);
      return response(url.pathname === "/api/v2/review/tasks" ? taskList : workspace());
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/papers/${ids.paper}`);
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    expect(requests.map((url) => url.pathname)).toEqual([
      "/api/v2/review/tasks",
      `/api/v2/workspaces/${ids.workspace}`,
    ]);
    expect(router.currentRoute.value.query.workspace).toBe(ids.workspace);
    expect(wrapper.get("h1").text()).toBe("Blank reviewer workspace");
  });

  it("renders an active Workspace read-only when an Admin inspects it", async () => {
    useAuthStore().acceptSession({
      user: { username: "admin", display_name: "管理员", role: "admin", must_change_password: false },
      csrf_token: "admin-csrf",
    });
    const calls: Array<{ url: URL; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: new URL(String(input), "http://leadtrace.test"), init });
      return response(workspace());
    }));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/review/papers/${ids.paper}?workspace=${ids.workspace}`);
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.get("[data-admin-readonly]").text()).toContain("只读");
    expect(wrapper.findAll("[data-section-choice]").every((button) => button.attributes("disabled") !== undefined)).toBe(true);
    await wrapper.get("[data-section-key='compounds'] [data-section-choice='completed']").trigger("click");
    await flushPromises();
    expect(calls.filter((call) => call.init?.method === "PUT")).toHaveLength(0);
  });

  it("reloads when the same Paper URL switches to a different Workspace query", async () => {
    const secondWorkspaceId = "10000000-0000-4000-8000-000000000006";
    const requests: URL[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://leadtrace.test");
      if (url.pathname.endsWith("/review-progress")) return response({},404);
      // Supporting lists are tested in their own components; count aggregate navigation here.
      if (['/compound-highlights','/evidence','/compounds'].some(x=>url.pathname.endsWith(x))) return response({workspace_id:ids.workspace,workspace_version:1,items:[],total:0});
      requests.push(url);
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

    await router.replace({ path: `/review/papers/${ids.paper}`, query: { workspace: secondWorkspaceId } });
    await flushPromises();

    expect(requests.map((url) => url.pathname)).toEqual([
      `/api/v2/workspaces/${ids.workspace}`,
      `/api/v2/workspaces/${secondWorkspaceId}`,
    ]);
    expect(wrapper.get("h1").text()).toBe("Reassigned Workspace");
    expect(wrapper.get("[data-workspace-version]").text()).toContain("v7");
  });
});

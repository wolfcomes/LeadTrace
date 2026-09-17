import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, ref } from "vue";
import { createMemoryHistory } from "vue-router";

import App from "../src/App.vue";
import AiPrefillStatus from "../src/admin/AiPrefillStatus.vue";
import { createAppRouter } from "../src/app/router";
import { useAuthStore } from "../src/auth/store";


const paperId = "20000000-0000-4000-8000-000000000001";
const workspaceId = "30000000-0000-4000-8000-000000000001";
const runId = "70000000-0000-4000-8000-000000000001";

function run(status: "queued" | "running" | "succeeded" | "failed" | "superseded") {
  return {
    id: runId,
    paper_id: paperId,
    workspace_id: workspaceId,
    starting_workspace_version: 1,
    status,
    engine: "legacy_pipeline",
    engine_version: "pilot-v1",
    error_summary: status === "failed" ? "AI extraction failed" : null,
    queued_at: "2026-09-17T06:00:00Z",
    started_at: status === "queued" ? null : "2026-09-17T06:00:01Z",
    completed_at: ["succeeded", "failed", "superseded"].includes(status)
      ? "2026-09-17T06:00:02Z"
      : null,
  };
}

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "X-Request-ID": "ai-prefill-ui" },
  });
}

describe("Admin AI paper prefill", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    useAuthStore().acceptSession({
      user: {
        username: "admin",
        display_name: "管理员",
        role: "admin",
        must_change_password: false,
      },
      csrf_token: "csrf-ai-prefill",
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("renders compact status without exposing an action", () => {
    const wrapper = mount(AiPrefillStatus, {
      props: {
        paperId,
        status: { run: run("failed"), can_start: true, blocked_reason: null },
        compact: true,
      },
    });

    expect(wrapper.get("[data-ai-prefill-status]").text()).toContain("预填失败");
    expect(wrapper.find("[data-ai-prefill-start]").exists()).toBe(false);
    expect(wrapper.text()).not.toContain("confidence");
  });

  it("starts once with CSRF and polls GET until the run succeeds", async () => {
    vi.useFakeTimers();
    const calls: Array<{ url: URL; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://leadtrace.test");
      calls.push({ url, init });
      if (init?.method === "POST") {
        return response({
          run: run("queued"),
          can_start: false,
          blocked_reason: "AI prefill is already queued or running",
        }, 202);
      }
      return response({
        run: run("succeeded"),
        can_start: false,
        blocked_reason: "Workspace has already been modified",
      });
    }));
    const wrapper = mount(AiPrefillStatus, {
      props: {
        paperId,
        status: { run: null, can_start: true, blocked_reason: null },
        interactive: true,
        poll: true,
      },
    });

    await wrapper.get("[data-ai-prefill-start]").trigger("click");
    await flushPromises();

    const posts = calls.filter((call) => call.init?.method === "POST");
    expect(posts).toHaveLength(1);
    expect(new Headers(posts[0]?.init?.headers).get("X-CSRF-Token")).toBe("csrf-ai-prefill");
    expect(wrapper.get("[data-ai-prefill-status]").text()).toContain("已排队");

    await vi.advanceTimersByTimeAsync(2_000);
    await flushPromises();

    expect(calls.filter((call) => call.init?.method === "POST")).toHaveLength(1);
    expect(calls.filter((call) => !call.init?.method)).toHaveLength(1);
    expect(wrapper.get("[data-ai-prefill-status]").text()).toContain("预填完成");
    wrapper.unmount();
    vi.useRealTimers();
  });

  it("offers failed runs as a retry but never replays a conflicting POST", async () => {
    const calls: Array<{ url: URL; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: new URL(String(input), "http://leadtrace.test"), init });
      return response({
        code: "AI_PREFILL_UNAVAILABLE",
        message: "AI prefill requires a blank, untouched editing Workspace",
        request_id: "ai-conflict",
        details: {},
      }, 409);
    }));
    const wrapper = mount(AiPrefillStatus, {
      props: {
        paperId,
        status: { run: run("failed"), can_start: true, blocked_reason: null },
        interactive: true,
      },
    });

    expect(wrapper.get("[data-ai-prefill-start]").text()).toContain("重新运行");
    await wrapper.get("[data-ai-prefill-start]").trigger("click");
    await flushPromises();

    expect(calls).toHaveLength(1);
    expect(calls[0]?.init?.method).toBe("POST");
    expect(wrapper.get("[data-ai-prefill-error]").text()).toContain("Workspace 已发生变化");
    expect(wrapper.get("[data-ai-prefill-error]").text()).toContain("ai-conflict");
  });

  it("mounts the interactive prefill control on the Admin paper detail", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response({
      id: paperId,
      paper_key: "LT-JMC-2024-67-05-001",
      title: "Selective kinase lead optimization",
      journal: "Journal of Medicinal Chemistry",
      publication_year: 2024,
      volume: "67",
      issue: "5",
      doi: "10.1021/acs.jmedchem.4c0001",
      catalog_state: "verified",
      source: {
        id: "50000000-0000-4000-8000-000000000001",
        asset_id: "60000000-0000-4000-8000-000000000001",
        source_root_key: "source_pdfs",
        source_key: "volume67 issue5/paper-01.pdf",
        sha256: "a".repeat(64),
        byte_size: 123456,
        page_count: 14,
        integrity_state: "verified",
      },
      review: {
        review_task_id: "40000000-0000-4000-8000-000000000001",
        workspace_id: workspaceId,
        assigned_reviewer_id: "10000000-0000-4000-8000-000000000002",
        assignee_display_name: "核查员一",
        task_status: "assigned",
        workspace_state: "editing",
        sections_resolved: 0,
        sections_total: 6,
        submission_state: "not_submitted",
      },
      ai_prefill: { run: null, can_start: true, blocked_reason: null },
    })));
    const router = createAppRouter(createMemoryHistory());
    await router.push(`/admin/papers/${paperId}`);
    await router.isReady();
    const wrapper = mount(App, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.get("[data-ai-prefill-panel]").text()).toContain("AI 预填");
    expect(wrapper.get("[data-ai-prefill-status]").text()).toContain("可启动");
    expect(wrapper.get("[data-ai-prefill-start]").attributes("disabled")).toBeUndefined();
  });

  it("stops polling after the bounded number of successful running reads", async () => {
    vi.useFakeTimers();
    let reads = 0;
    const running = {
      run: run("running"),
      can_start: false,
      blocked_reason: "AI prefill is already queued or running",
    };
    vi.stubGlobal("fetch", vi.fn(async () => {
      reads += 1;
      return response(running);
    }));
    const Harness = defineComponent({
      components: { AiPrefillStatus },
      setup() {
        const status = ref(running);
        return { paperId, status };
      },
      template: `<AiPrefillStatus :paper-id="paperId" :status="status" poll @update="status = $event" />`,
    });
    const wrapper = mount(Harness);

    await vi.advanceTimersByTimeAsync(70_000);
    await flushPromises();

    const completedReads = reads;
    wrapper.unmount();
    vi.useRealTimers();
    expect(completedReads).toBe(30);
  });
});

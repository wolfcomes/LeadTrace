import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";

import App from "../src/App.vue";
import { createAppRouter } from "../src/app/router";
import { useAuthStore } from "../src/auth/store";
import {
  adminSubmissionDetail,
  adminSubmissionList,
  decisionMutation,
  jsonResponse,
  publicationIds,
  submission,
} from "./paper-publication-v2-fixtures";


function installAdmin(): void {
  setActivePinia(createPinia());
  useAuthStore().acceptSession({
    user: { username: "admin", display_name: "Admin", role: "admin", must_change_password: false },
    csrf_token: "admin-csrf",
  });
}

async function mountAt(path: string) {
  const router = createAppRouter(createMemoryHistory());
  await router.push(path);
  await router.isReady();
  const wrapper = mount(App, { global: { plugins: [router] } });
  await flushPromises();
  return { wrapper, router };
}

describe("paper-centric Admin approval", () => {
  beforeEach(installAdmin);
  afterEach(() => vi.unstubAllGlobals());

  it("lists pending submissions and opens the frozen Paper review", async () => {
    const requests: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      requests.push(path);
      if (path === "/api/v2/admin/submissions") return jsonResponse(adminSubmissionList);
      if (path === `/api/v2/admin/submissions/${publicationIds.submission}`) {
        return jsonResponse(adminSubmissionDetail);
      }
      throw new Error(`Unexpected request: ${path}`);
    }));

    const { wrapper, router } = await mountAt("/admin/submissions");

    expect(wrapper.get("[data-submission-row]").text()).toContain("Approved lead optimization study");
    expect(wrapper.get("[data-submission-row]").text()).toContain("第 2 次提交");
    await wrapper.get("[data-open-submission]").trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.path).toBe(`/admin/submissions/${publicationIds.submission}`);
    expect(wrapper.get("[data-submission-review]").text()).toContain(submission.content_hash);
    expect(wrapper.get("[data-submission-review]").text()).toContain("All structures and transformations checked");
    expect(wrapper.get("[data-submission-lineage]").text()).toContain("Series A");
    expect(wrapper.get("[data-submission-lineage]").text()).toContain("Polar amine replacement");
    expect(wrapper.get("[data-structure-comparison]").text()).toContain("Lead 1");
    expect(wrapper.get("[data-source-pdf]").attributes("href"))
      .toBe(`/api/v2/papers/${publicationIds.paper}/source-pdf`);
    expect(wrapper.get("[data-structure-source-image]").attributes("src"))
      .toBe(`/api/v2/structure-source-images/${publicationIds.sourceImage}/content`);
    expect(wrapper.get("[data-rdkit-depiction]").attributes("src")).toContain(publicationIds.depictionA);
    expect(wrapper.get("[data-submission-lineage]").text()).toContain("root");
    expect(wrapper.get("[data-submission-lineage]").text()).toContain("terminal");
    expect(wrapper.get("[data-submission-evidence]").text()).toContain("Lead 1 was optimized to compound 18.");
    expect(wrapper.get("[data-evidence-pdf-locator]").attributes("href"))
      .toBe(`/api/v2/papers/${publicationIds.paper}/source-pdf#page=4`);
    expect(wrapper.get("[data-submission-evidence]").text()).toContain("Lead 1 → Compound 18");
    expect(wrapper.get("[data-submission-evidence]").text()).toContain("IC50");
    expect(wrapper.get("[data-submission-evidence]").text()).toContain("12.5 nM");
    expect(wrapper.get("[data-reviewer-diff]").text()).toContain("CCO");
    expect(requests).toEqual([
      "/api/v2/admin/submissions",
      `/api/v2/admin/submissions/${publicationIds.submission}`,
    ]);
  });

  it("requires a reason, uses the frozen hash, and publishes exactly once", async () => {
    let decisionRequests = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (path === `/api/v2/admin/submissions/${publicationIds.submission}` && !init?.method) {
        return jsonResponse(adminSubmissionDetail);
      }
      if (path.endsWith("/decisions")) {
        decisionRequests += 1;
        const headers = new Headers(init?.headers);
        const body = JSON.parse(String(init?.body));
        expect(headers.get("X-CSRF-Token")).toBe("admin-csrf");
        expect(headers.get("Idempotency-Key")).toBe(
          `approve-${publicationIds.submission}-${submission.content_hash}`,
        );
        expect(body).toEqual({
          content_hash: submission.content_hash,
          action: "approve",
          reason: "Scientific record verified.",
        });
        return jsonResponse(decisionMutation("approve"));
      }
      throw new Error(`Unexpected request: ${path}`);
    }));

    const { wrapper } = await mountAt(`/admin/submissions/${publicationIds.submission}`);
    expect(wrapper.get("[data-approve-submission]").attributes()).toHaveProperty("disabled");

    await wrapper.get("[data-decision-reason]").setValue("Scientific record verified.");
    await wrapper.get("[data-approve-submission]").trigger("click");
    await wrapper.get("[data-approve-submission]").trigger("click");
    await flushPromises();

    expect(decisionRequests).toBe(1);
    expect(wrapper.get("[data-decision-success]").text()).toContain("已批准并发布");
    expect(wrapper.get("[data-published-paper-link]").attributes("href"))
      .toBe(`/papers/${publicationIds.paper}`);
  });

  it("returns the frozen submission for changes with a stable request key", async () => {
    let requestBody: Record<string, unknown> | null = null;
    let idempotencyKey = "";
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      if (!init?.method) return jsonResponse(adminSubmissionDetail);
      requestBody = JSON.parse(String(init.body));
      idempotencyKey = new Headers(init.headers).get("Idempotency-Key") ?? "";
      return jsonResponse(decisionMutation("request_changes"));
    }));

    const { wrapper } = await mountAt(`/admin/submissions/${publicationIds.submission}`);
    await wrapper.get("[data-decision-reason]").setValue("Please clarify the terminal structure.");
    await wrapper.get("[data-request-changes]").trigger("click");
    await flushPromises();

    expect(requestBody).toMatchObject({ action: "request_changes", content_hash: submission.content_hash });
    expect(idempotencyKey).toBe(
      `request_changes-${publicationIds.submission}-${submission.content_hash}`,
    );
    expect(wrapper.get("[data-decision-success]").text()).toContain("已退回 Reviewer 修改");
  });
});

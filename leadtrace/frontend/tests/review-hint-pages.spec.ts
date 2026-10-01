import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";

import PaperSubmissionReviewPage from "../src/approvals/PaperSubmissionReviewPage.vue";
import { useAuthStore } from "../src/auth/store";
import PaperDetailPage from "../src/papers/PaperDetailPage.vue";
import {
  adminSubmissionDetail,
  jsonResponse,
  publicationIds,
  publishedDetail,
} from "./paper-publication-v2-fixtures";

enableAutoUnmount(afterEach);
afterEach(() => vi.unstubAllGlobals());
beforeEach(() => {
  setActivePinia(createPinia());
  useAuthStore().acceptSession({
    user: { username: "admin", display_name: "Admin", role: "admin", must_change_password: false },
    csrf_token: "admin-csrf",
  });
});

const hints = {
  compound: "Shared core supports the structure; verify ring closure.",
  activity: "Table and text disagree; the table value is retained.",
  edge: "Reaction family supports this connection; verify individual pairing.",
};

describe.each(["submission", "published"] as const)("%s page review hints", (page) => {
  async function openPage(withHints: boolean) {
    const source = page === "submission"
      ? adminSubmissionDetail.submission.snapshot
      : publishedDetail.snapshot;
    const snapshot = {
      ...source,
      compounds: source.compounds.map((row, index) => ({
        ...row, ...(withHints && index === 0 ? { review_hint: hints.compound } : {}),
      })),
      activities: source.activities.map(row => ({
        ...row, ...(withHints ? { review_hint: hints.activity } : {}),
      })),
      lineage_edges: source.lineage_edges.map(row => ({
        ...row, ...(withHints ? { review_hint: hints.edge } : {}),
      })),
    };
    const payload = page === "submission"
      ? { ...adminSubmissionDetail, submission: { ...adminSubmissionDetail.submission, snapshot } }
      : { ...publishedDetail, snapshot };
    const endpoint = page === "submission"
      ? "/api/v2/admin/submissions/" + publicationIds.submission
      : "/api/v2/papers/" + publicationIds.paper;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(new URL(String(input), "http://leadtrace.test").pathname).toBe(endpoint);
      expect(init?.method ?? "GET").toBe("GET");
      return jsonResponse(payload);
    });
    vi.stubGlobal("fetch", fetchMock);
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: "/admin/submissions", name: "admin-submissions", component: { template: "<div />" } },
        { path: "/admin/submissions/:submissionId", component: PaperSubmissionReviewPage },
        { path: "/papers", name: "papers", component: { template: "<div />" } },
        { path: "/papers/:paperId", name: "paper-detail", component: PaperDetailPage },
      ],
    });
    await router.push(endpoint.replace("/api/v2", ""));
    await router.isReady();
    const wrapper = page === "submission"
      ? mount(PaperSubmissionReviewPage, { global: { plugins: [router] } })
      : mount(PaperDetailPage, { global: { plugins: [router] } });
    await flushPromises();
    return { wrapper, fetchMock };
  }

  it("discloses frozen compound, activity and confirmed-edge hints without editing them", async () => {
    const { wrapper, fetchMock } = await openPage(true);
    const disclosures = wrapper.findAll("[data-review-hint]");
    expect(disclosures).toHaveLength(3);
    expect(wrapper.find("[role=note]").exists()).toBe(false);
    for (const disclosure of disclosures) {
      const button = disclosure.get("button");
      expect(button.text()).toBe("⚠");
      await button.trigger("click");
      expect(button.attributes("aria-expanded")).toBe("true");
    }
    expect(wrapper.findAll("[role=note]").map(note => note.text()).sort())
      .toEqual(Object.values(hints).sort());
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(wrapper.find("[data-edit-compound-review-hint]").exists()).toBe(false);
    expect(wrapper.find("[data-edit-activity-review-hint]").exists()).toBe(false);
    expect(wrapper.find("[data-edit-edge-review-hint]").exists()).toBe(false);
  });

  it("keeps legacy snapshots without hints free of warning symbols", async () => {
    const { wrapper, fetchMock } = await openPage(false);
    expect(wrapper.text()).toContain("Lead 1");
    expect(wrapper.text()).toContain("12.5 nM");
    expect(wrapper.find("[data-review-hint]").exists()).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

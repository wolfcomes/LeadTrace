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

  it("navigates actual Reviewer versions with dates and keeps old decisions read-only", async () => {
    const olderId = '00000000-0000-4000-8000-000000000777';
    const version = (id: string, round: number) => ({
      id, paper_id: submission.paper_id, workspace_id: submission.workspace_id,
      submission_number: round === 1 ? 1 : 4, round_number: round,
      submitted_by_id: submission.submitted_by_id, submitted_by_name: 'Original Reviewer',
      submitted_at: round === 1 ? '2026-10-10T02:00:00Z' : '2026-10-15T04:00:00Z',
      content_hash: submission.content_hash, reviewer_note: 'Reviewer note',
      status: round === 1 ? 'supplemented' : 'pending', decision: null,
    });
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const older = String(input).includes(olderId);
      return jsonResponse({ ...structuredClone(adminSubmissionDetail),
        submission: { ...structuredClone(submission), id: older ? olderId : submission.id },
        review_rounds: { requested_submission_id: older ? olderId : submission.id,
          selected_round_number: older ? 1 : 2, can_decide: !older,
          versions: [version(olderId, 1), version(submission.id, 2)], supplements: [], warnings: [] },
      });
    }));
    const { wrapper, router } = await mountAt(`/admin/submissions/${publicationIds.submission}`);
    const navigation = wrapper.get('[data-review-version-navigation]');
    expect(navigation.text()).toContain('第 2 / 2 次提交');
    expect(navigation.text()).toContain('Original Reviewer');
    expect(navigation.text()).toContain('2026');
    await wrapper.get('[data-decision-reason]').setValue('Do not carry this to another version');
    await wrapper.get('[data-previous-review-version]').trigger('click');
    await flushPromises();
    expect(router.currentRoute.value.path).toContain(olderId);
    expect(wrapper.get('[data-review-version-navigation]').text()).toContain('第 1 / 2 次提交');
    expect(wrapper.find('[data-approve-submission]').exists()).toBe(false);
    expect(wrapper.get('[data-historical-review]').text()).toContain('只读');
    await wrapper.get('[data-next-review-version]').trigger('click');
    await flushPromises();
    expect((wrapper.get('[data-decision-reason]').element as HTMLTextAreaElement).value).toBe('');
  });

  it('keeps post-submit AI supplements folded and outside the Reviewer comparison', async () => {
    const after = structuredClone(submission.snapshot);
    Object.assign(after.paper, { abstract: 'AI-only abstract' });
    const original = { ...structuredClone(adminSubmissionDetail), review_rounds: {
      requested_submission_id: submission.id, selected_round_number: 1, can_decide: false,
      versions: [{ id: submission.id, paper_id: submission.paper_id, workspace_id: submission.workspace_id,
        submission_number: submission.submission_number, round_number: 1,
        submitted_by_id: submission.submitted_by_id, submitted_by_name: 'Reviewer',
        submitted_at: submission.submitted_at, content_hash: submission.content_hash,
        reviewer_note: submission.reviewer_note, status: 'awaiting_reviewer', decision: null }],
      supplements: [{ phase: 'after_submission', count: 2, submitted_at: submission.submitted_at,
        snapshot: after, comparison: { kind: 'previous_submission', baseline_submission_number: null,
          baseline_snapshot: submission.snapshot, events: [], warnings: [] } }], warnings: [] } };
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(original)));
    const { wrapper } = await mountAt(`/admin/submissions/${publicationIds.submission}`);
    const panel = wrapper.get('[data-ai-supplements]');
    expect(panel.attributes('open')).toBeUndefined();
    expect(panel.text()).toContain('提交后补填');
    expect(wrapper.text()).not.toContain('AI-only abstract');
    expect(wrapper.find('[data-approve-submission]').exists()).toBe(false);
    (panel.element as HTMLDetailsElement).open = true;
    await panel.trigger('toggle');
    expect(panel.text()).toContain('AI-only abstract');
  });

  it('filters pending Reviewer submissions while retaining access to returned versions', async () => {
    const technicalId = '00000000-0000-4000-8000-000000000778';
    const items = [{ ...adminSubmissionList.items[0], reviewer_round_number: 1,
      review_entry_id: technicalId, submitted_by_name: 'Reviewer', review_status: 'awaiting_reviewer' }];
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items, total: 1 })));
    const { wrapper } = await mountAt('/admin/submissions');
    expect(wrapper.find('[data-submission-row]').exists()).toBe(false);
    await wrapper.get('[data-all-review-submissions]').trigger('click');
    expect(wrapper.get('[data-submission-row]').text()).toContain('待 Reviewer 核对补填');
    expect(wrapper.get('[data-submission-row]').text()).toContain('第 1 次提交');
    expect(wrapper.get('[data-open-submission]').attributes('href')).toBe(`/admin/submissions/${technicalId}`);
  });

  it("shows the originating Reviewer note separately after metadata supplements", async () => {
    const originalId = "00000000-0000-4000-8000-000000000777";
    const payload = { ...structuredClone(adminSubmissionDetail),
      submission: { ...structuredClone(adminSubmissionDetail.submission), reviewer_note: null },
    };
    const comparison = {
      kind: "reviewer_start", baseline_submission_number: null,
      baseline_snapshot: structuredClone(submission.snapshot), events: [], warnings: [],
      supplement_count: 2,
      reviewer_submission: {
        id: originalId, paper_id: submission.paper_id, workspace_id: submission.workspace_id,
        submission_number: 1, submitted_by_id: submission.submitted_by_id,
        submitted_at: submission.submitted_at, content_hash: "a".repeat(64),
        reviewer_note: "Original review caveat remains important",
      },
    };
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ ...payload, comparison })));
    const { wrapper } = await mountAt(`/admin/submissions/${publicationIds.submission}`);
    const origin = wrapper.get("[data-original-reviewer-submission]");
    expect(origin.text()).toContain("Original review caveat remains important");
    expect(origin.text()).toContain("后续补填内容仍需审批");
    expect(origin.get("a").attributes("href")).toBe(`/admin/submissions/${originalId}`);
    expect(wrapper.find(".reviewer-attestation").exists()).toBe(false);
    expect(wrapper.get("[data-submission-review]").text()).toContain(submission.content_hash);
  });

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
    expect(wrapper.get("[data-comparison-warning]").text()).toContain("比较起点不可用");
    expect(wrapper.find("[data-submission-lineage]").exists()).toBe(false);
    const fullContent = wrapper.get("[data-full-submission]");
    (fullContent.element as HTMLDetailsElement).open = true;
    await fullContent.trigger("toggle");
    expect(wrapper.get("[data-submission-lineage]").text()).toContain("Series A");
    expect(wrapper.get("[data-submission-lineage]").text()).toContain("Polar amine replacement");
    expect(wrapper.get("[data-structure-comparison]").text()).toContain("Lead 1");
    expect(wrapper.get("[data-source-pdf]").attributes("href"))
      .toBe(`/api/v2/papers/${publicationIds.paper}/source-pdf`);
    expect(wrapper.get("[data-structure-comparison] [data-frozen-evidence]").text()).toContain("Scheme 1");
    expect(wrapper.find('img[src*="structure-source-images"]').exists()).toBe(false);
    expect(wrapper.get("[data-rdkit-depiction]").attributes("src")).toContain(publicationIds.depictionA);
    expect(wrapper.get("[data-submission-lineage]").text()).toContain("root");
    expect(wrapper.get("[data-submission-lineage]").text()).toContain("terminal");
    expect(wrapper.get("[data-submission-evidence]").text()).toContain("Lead 1 was optimized to compound 18.");
    expect(wrapper.get("[data-submission-evidence] [data-evidence-pdf-locator]").attributes("href"))
      .toBe(`/api/v2/papers/${publicationIds.paper}/source-pdf#page=4`);
    expect(wrapper.get("[data-submission-evidence]").text()).toContain("Lead 1 → Compound 18");
    expect(wrapper.get("[data-submission-evidence]").text()).toContain("IC50");
    expect(wrapper.get("[data-submission-evidence]").text()).toContain("12.5 nM");
    const history = wrapper.get("[data-change-history]");
    (history.element as HTMLDetailsElement).open = true;
    await history.trigger("toggle");
    expect(wrapper.get("[data-reviewer-diff]").text()).toContain("CCO");
    expect(wrapper.get("[data-reviewer-diff]").text()).toContain("AI 预填");
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

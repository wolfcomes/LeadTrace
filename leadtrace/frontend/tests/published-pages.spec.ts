import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";

import OverviewPage from "../src/papers/OverviewPage.vue";
import PaperDetailPage from "../src/papers/PaperDetailPage.vue";
import PaperLibraryPage from "../src/papers/PaperLibraryPage.vue";


const release = {
  id: "10000000-0000-4000-8000-000000000001",
  key: "baseline-2026-09-11",
  title: "LeadTrace verified baseline",
  published_at: "2026-09-11T01:00:00+00:00",
};

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      "X-Request-ID": "published-page-request",
    },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("published overview", () => {
  it("renders six explicit release metrics without a legacy aggregate", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(200, {
      request_id: "published-page-request",
      release,
      metrics: {
        corpus: { numerator: 672, denominator: 672, unit: "papers" },
        lineage: { numerator: 138, denominator: 672, unit: "papers" },
        relation: { numerator: 4144, denominator: 4144, unit: "edges" },
        structure: { numerator: 4011, denominator: 4301, unit: "compounds" },
        pair: { numerator: 1730, denominator: 4144, unit: "edges" },
        human_review: { numerator: 0, denominator: 672, unit: "papers" },
      },
    })));

    const wrapper = mount(OverviewPage);
    await flushPromises();

    expect(wrapper.get("[data-metric='lineage']").text()).toContain("138 / 672");
    expect(wrapper.text()).toContain("文献语料");
    expect(wrapper.text()).toContain("谱系覆盖");
    expect(wrapper.text()).toContain("关系质量");
    expect(wrapper.text()).toContain("结构质量");
    expect(wrapper.text()).toContain("配对就绪");
    expect(wrapper.text()).toContain("人工核查");
    expect(wrapper.text()).not.toContain("16-path");
    expect(wrapper.text()).not.toContain("总体完成度");
  });

  it("shows a stable empty state when no current release exists", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(404, {
      code: "CURRENT_RELEASE_NOT_FOUND",
      message: "No published release is currently available",
      details: {},
      request_id: "published-page-request",
    })));

    const wrapper = mount(OverviewPage);
    await flushPromises();

    expect(wrapper.get("[data-empty-state]").text()).toContain("暂无发布版本");
    expect(wrapper.text()).not.toContain("草稿");
    expect(wrapper.text()).not.toContain("导入候选");
  });
});

describe("published Paper library", () => {
  it("restores filters from the URL, uses server pagination, and preserves filters when searching", async () => {
    const requests: URL[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://leadtrace.test");
      requests.push(url);
      return jsonResponse(200, {
        request_id: "published-page-request",
        release,
        pagination: { page: 2, page_size: 20, total_items: 25, total_pages: 2 },
        filters: {
          search: url.searchParams.get("search"),
          doi: null,
          target: url.searchParams.get("target"),
          has_lineage: url.searchParams.get("has_lineage"),
          relation_status: null,
          structure_state: null,
          review_status: url.searchParams.get("review_status"),
          sort: "manifest",
        },
        items: [{
          id: "20000000-0000-4000-8000-000000000001",
          revision_id: "20000000-0000-4000-8000-000000000002",
          paper_key: "paper-24",
          doi: "10.1000/paper-24",
          title: "Published optimization study 24",
          year: "2026",
          target: "Kinase A",
          review_status: "unreviewed",
        }],
      });
    }));
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: "/papers", name: "papers", component: PaperLibraryPage },
        { path: "/papers/:paperId", name: "paper-detail", component: { template: "<div />" } },
      ],
    });
    await router.push("/papers?search=kinase&target=Kinase%20A&has_lineage=true&review_status=unreviewed&page=2");
    await router.isReady();

    const wrapper = mount(PaperLibraryPage, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.get("#paper-search").element).toHaveProperty("value", "kinase");
    expect(wrapper.get("#paper-target").element).toHaveProperty("value", "Kinase A");
    expect(wrapper.text()).toContain("paper-24");
    expect(wrapper.text()).toContain("10.1000/paper-24");
    expect(wrapper.text()).toContain("Published optimization study 24");
    expect(wrapper.text()).toContain("第 2 / 2 页");
    expect(requests[0].searchParams.get("page")).toBe("2");
    expect(requests[0].searchParams.get("has_lineage")).toBe("true");

    await wrapper.get("#paper-search").setValue("protease");
    await wrapper.get("[data-filter-form]").trigger("submit");
    await flushPromises();

    expect(router.currentRoute.value.query).toMatchObject({
      search: "protease",
      target: "Kinase A",
      has_lineage: "true",
      review_status: "unreviewed",
      page: "1",
    });
  });
});

describe("published Paper detail", () => {
  it("separates confirmed structures, unresolved relations, evidence, and quality", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(200, {
      request_id: "published-page-request",
      release,
      paper: {
        id: "20000000-0000-4000-8000-000000000001",
        revision_id: "20000000-0000-4000-8000-000000000002",
        paper_key: "paper-24",
        doi: "10.1000/paper-24",
        title: "Published optimization study 24",
        year: "2026",
        target: "Kinase A",
        review_status: "unreviewed",
      },
      compounds: [
        { id: "30000000-0000-4000-8000-000000000001", revision_id: "31000000-0000-4000-8000-000000000001", local_identity: "CMP-PARENT", label: "26a′" },
        { id: "30000000-0000-4000-8000-000000000002", revision_id: "31000000-0000-4000-8000-000000000002", local_identity: "CMP-DERIVED", label: "26b" },
        { id: "30000000-0000-4000-8000-000000000003", revision_id: "31000000-0000-4000-8000-000000000003", local_identity: "CMP-UNRESOLVED", label: "27" },
      ],
      lineages: [{ id: "40000000-0000-4000-8000-000000000001", revision_id: "41000000-0000-4000-8000-000000000001", lineage_key: "LINEAGE-1" }],
      lineage_edges: [
        { id: "50000000-0000-4000-8000-000000000001", revision_id: "51000000-0000-4000-8000-000000000001", lineage_id: "40000000-0000-4000-8000-000000000001", parent_compound_id: "30000000-0000-4000-8000-000000000001", derived_compound_id: "30000000-0000-4000-8000-000000000002", relation_type: "direct_optimization", relation_status: "text_explicit", pair_ready: true },
        { id: "50000000-0000-4000-8000-000000000002", revision_id: "51000000-0000-4000-8000-000000000002", lineage_id: "40000000-0000-4000-8000-000000000001", parent_compound_id: null, derived_compound_id: "30000000-0000-4000-8000-000000000003", relation_type: null, relation_status: "unresolved", pair_ready: false },
      ],
      structures: [
        { id: "60000000-0000-4000-8000-000000000001", revision_id: "61000000-0000-4000-8000-000000000001", compound_id: "30000000-0000-4000-8000-000000000002", state: "structure_confirmed", canonical_smiles: "CCN" },
        { id: "60000000-0000-4000-8000-000000000002", revision_id: "61000000-0000-4000-8000-000000000002", compound_id: "30000000-0000-4000-8000-000000000003", state: "source_mismatch", canonical_smiles: "FAKE-SCREENSHOT-SMILES" },
      ],
      evidence: [{ id: "70000000-0000-4000-8000-000000000001", revision_id: "71000000-0000-4000-8000-000000000001", state: "confirmed", text: "Potency improved." }],
      activities: [{ id: "80000000-0000-4000-8000-000000000001", revision_id: "81000000-0000-4000-8000-000000000001", compound_id: "30000000-0000-4000-8000-000000000002", state: "confirmed", metric: "IC50", value: "12", unit: "nM", qualifier: "=" }],
      quality_summary: {
        relations: { resolved: 1, total: 2 },
        structures: { confirmed: 1, total: 2 },
        pair_ready: { eligible: 1, total: 2 },
        human_review: { reviewed: 0, total: 12 },
      },
    })));
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: "/papers", name: "papers", component: { template: "<div />" } },
        { path: "/papers/:paperId", name: "paper-detail", component: PaperDetailPage },
      ],
    });
    await router.push("/papers/20000000-0000-4000-8000-000000000001");
    await router.isReady();

    const wrapper = mount(PaperDetailPage, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.text()).toContain("paper-24");
    expect(wrapper.text()).toContain("10.1000/paper-24");
    expect(wrapper.text()).toContain("LINEAGE-1");
    expect(wrapper.get("[data-edge-status='unresolved']").text()).toContain("关系待解析");
    expect(wrapper.findAll("[data-molecule-pair]")).toHaveLength(1);
    expect(wrapper.get("[data-confirmed-structure]").text()).toContain("CCN");
    expect(wrapper.text()).not.toContain("FAKE-SCREENSHOT-SMILES");
    expect(wrapper.text()).toContain("已核查证据");
    expect(wrapper.text()).toContain("Potency improved.");
    expect(wrapper.text()).toContain("IC50");
    expect(wrapper.text()).toContain("1 / 2");
  });
});

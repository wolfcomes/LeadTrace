import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";

import PaperDetailPage from "../src/papers/PaperDetailPage.vue";
import PaperLibraryPage from "../src/papers/PaperLibraryPage.vue";
import {
  jsonResponse,
  publicationIds,
  publishedDetail,
  publishedList,
} from "./paper-publication-v2-fixtures";


function publishedRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/papers", name: "papers", component: PaperLibraryPage },
      { path: "/papers/:paperId", name: "paper-detail", component: PaperDetailPage },
    ],
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("paper-centric published pages", () => {
  it("lists only immutable Published Paper Versions and opens their snapshot", async () => {
    const requests: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://leadtrace.test");
      requests.push(url.pathname);
      if (url.pathname === "/api/v2/papers") return jsonResponse(publishedList);
      if (url.pathname === `/api/v2/papers/${publicationIds.paper}`) return jsonResponse(publishedDetail);
      throw new Error(`Unexpected request: ${url.pathname}`);
    }));
    const router = publishedRouter();
    await router.push("/papers");
    await router.isReady();
    const wrapper = mount(PaperLibraryPage, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.get("[data-published-paper-row]").text()).toContain("Approved lead optimization study");
    expect(wrapper.get("[data-published-paper-row]").text()).toContain("Journal of Medicinal Chemistry");
    expect(wrapper.get("[data-published-paper-row]").text()).toContain("67(5)");
    expect(wrapper.get("[data-published-paper-row]").text()).toContain("版本 1");

    await wrapper.get("[data-open-published-paper]").trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.path).toBe(`/papers/${publicationIds.paper}`);
    wrapper.unmount();
    const detailWrapper = mount(PaperDetailPage, { global: { plugins: [router] } });
    await flushPromises();

    expect(detailWrapper.get("[data-published-paper-detail]").text()).toContain("Series A");
    expect(detailWrapper.get("[data-published-paper-detail]").text()).toContain("Lead 1 → Compound 18");
    expect(detailWrapper.get("[data-published-paper-detail]").text()).toContain("root");
    expect(detailWrapper.get("[data-published-paper-detail]").text()).toContain("terminal");
    expect(detailWrapper.get("[data-published-paper-detail]").text()).toContain("supports · Lead 1 → Compound 18");
    expect(detailWrapper.get("[data-published-paper-detail]").text()).toContain("IC50");
    expect(detailWrapper.get("[data-published-paper-detail]").text()).toContain("12.5 nM");
    expect(detailWrapper.get("[data-published-depiction]").attributes("src"))
      .toBe(`/api/v2/papers/${publicationIds.paper}/assets/${publicationIds.depictionA}`);
    expect(detailWrapper.get("[data-published-evidence-crop]").attributes("src"))
      .toBe(`/api/v2/papers/${publicationIds.paper}/assets/${publicationIds.evidenceCrop}`);
    expect(requests).toEqual(["/api/v2/papers", `/api/v2/papers/${publicationIds.paper}`]);
    expect(requests.some((path) => path.includes("workspaces"))).toBe(false);
  });

  it("conceals an unpublished Paper as not found", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({
      code: "RESOURCE_NOT_FOUND",
      message: "Resource not found",
      details: {},
      request_id: "task16-ui",
    }, 404)));
    const router = publishedRouter();
    await router.push(`/papers/${publicationIds.paper}`);
    await router.isReady();
    const wrapper = mount(PaperDetailPage, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.get("[data-published-not-found]").text()).toContain("未找到已批准文章");
    expect(wrapper.text()).not.toContain("Workspace");
  });
});

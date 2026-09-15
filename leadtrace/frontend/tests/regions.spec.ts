import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import PdfReviewCanvas from "../src/pdf-viewer/PdfReviewCanvas.vue";

describe("PDF region review canvas", () => {
  it("emits normalized rectangle coordinates when drawing on a page", async () => {
    const wrapper = mount(PdfReviewCanvas, {
      props: {
        pdfUrl: "/api/v1/papers/paper-1/source-pdf?kind=article",
        pageCount: 1,
        regions: [],
      },
    });

    expect(wrapper.get(".canvas-toolbar").classes()).toContain("workspace-toolbar");
    expect(wrapper.get(".canvas-toolbar input").classes()).toContain("form-control");
    expect(wrapper.get(".canvas-toolbar button").classes()).toContain("button-quiet");
    const canvas = wrapper.get("[data-pdf-page]");
    await canvas.trigger("pointerdown", { clientX: 100, clientY: 50 });
    await canvas.trigger("pointermove", { clientX: 300, clientY: 250 });
    await canvas.trigger("pointerup", { clientX: 300, clientY: 250 });

    expect(wrapper.emitted("create-region")).toEqual([
      [{ pageNumber: 1, x0: 0.125, y0: 0.125, x1: 0.375, y1: 0.625, rotation: 0 }],
    ]);
  });

  it("renders region overlays with accessible selection controls", () => {
    const wrapper = mount(PdfReviewCanvas, {
      props: {
        pdfUrl: "/source.pdf",
        pageCount: 1,
        regions: [{ id: "r1", pageNumber: 1, x0: 0.1, y0: 0.2, x1: 0.4, y1: 0.5, rotation: 0 }],
      },
    });

    expect(wrapper.get("[data-region-id='r1']").attributes("role")).toBe("button");
    expect(wrapper.get("[data-region-id='r1']").attributes("aria-label")).toContain("r1");
  });

  it("does not create regions in read-only mode", async () => {
    const wrapper = mount(PdfReviewCanvas, {
      props: {
        pdfUrl: "/source.pdf",
        pageCount: 1,
        regions: [],
        readOnly: true,
      },
    });

    const canvas = wrapper.get("[data-pdf-page]");
    await canvas.trigger("pointerdown", { clientX: 100, clientY: 50 });
    await canvas.trigger("pointermove", { clientX: 300, clientY: 250 });
    await canvas.trigger("pointerup", { clientX: 300, clientY: 250 });

    expect(wrapper.emitted("create-region")).toBeUndefined();
  });

  it("emits normalized coordinates when moving and resizing a Region", async () => {
    const wrapper = mount(PdfReviewCanvas, {
      props: {
        pdfUrl: "/source.pdf",
        pageCount: 1,
        regions: [{ id: "r1", pageNumber: 1, x0: 0.1, y0: 0.2, x1: 0.4, y1: 0.5, rotation: 0 }],
        selectedRegionId: "r1",
      },
    });

    const region = wrapper.get("[data-region-id='r1']");
    await region.trigger("pointerdown", { pointerId: 1, clientX: 80, clientY: 80 });
    await region.trigger("pointermove", { pointerId: 1, clientX: 160, clientY: 120 });
    await region.trigger("pointerup", { pointerId: 1, clientX: 160, clientY: 120 });

    expect(wrapper.emitted("move-region")).toEqual([[
      { id: "r1", pageNumber: 1, x0: 0.2, y0: 0.3, x1: 0.5, y1: 0.6, rotation: 0 },
    ]]);

    const handle = wrapper.get("[data-resize-handle='se']");
    await handle.trigger("pointerdown", { pointerId: 2, clientX: 320, clientY: 200 });
    await handle.trigger("pointermove", { pointerId: 2, clientX: 400, clientY: 240 });
    await handle.trigger("pointerup", { pointerId: 2, clientX: 400, clientY: 240 });

    expect(wrapper.emitted("resize-region")).toEqual([[
      { id: "r1", pageNumber: 1, x0: 0.1, y0: 0.2, x1: 0.5, y1: 0.6, rotation: 0 },
    ]]);
  });

  it("synchronizes an externally selected Region and page", async () => {
    const wrapper = mount(PdfReviewCanvas, {
      props: {
        pdfUrl: "/source.pdf",
        pageCount: 2,
        page: 2,
        selectedRegionId: "r2",
        regions: [
          { id: "r1", pageNumber: 1, x0: 0.1, y0: 0.2, x1: 0.4, y1: 0.5, rotation: 0 },
          { id: "r2", pageNumber: 2, x0: 0.2, y0: 0.3, x1: 0.5, y1: 0.6, rotation: 0 },
        ],
      },
    });

    expect(wrapper.get("[data-pdf-page]").attributes("data-page-number")).toBe("2");
    expect(wrapper.get("[data-region-id='r2']").classes()).toContain("selected");

    await wrapper.setProps({ page: 1, selectedRegionId: "r1" });
    expect(wrapper.get("[data-pdf-page]").attributes("data-page-number")).toBe("1");
    expect(wrapper.get("[data-region-id='r1']").classes()).toContain("selected");
  });

  it("renders a real PDF canvas with a protected document fallback", () => {
    const wrapper = mount(PdfReviewCanvas, {
      props: {
        pdfUrl: "/api/v1/papers/paper-1/source-pdf?kind=article",
        pageCount: 2,
        regions: [],
      },
    });

    expect(wrapper.get("[data-pdf-canvas]").element.tagName).toBe("CANVAS");
    expect(wrapper.find(".pdf-page-shell").exists()).toBe(true);
    expect(wrapper.get(".pdf-fallback").attributes("src")).toContain("source-pdf");
  });
});

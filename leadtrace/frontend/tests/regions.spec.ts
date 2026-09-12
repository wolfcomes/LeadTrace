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
});

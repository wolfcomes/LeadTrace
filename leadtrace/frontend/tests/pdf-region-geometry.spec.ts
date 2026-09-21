import { describe, expect, it } from "vitest";

import { normalizePdfRegionBounds } from "../src/pdf-viewer/geometry";


describe("normalizePdfRegionBounds", () => {
  it("rounds production PDF coordinates to ten decimal places", () => {
    expect(normalizePdfRegionBounds({
      x0: 0.15683718909525357,
      y0: 0.22703818369453047,
      x1: 0.6357481626298831,
      y1: 0.7391812865497076,
    })).toEqual({
      x0: 0.1568371891,
      y0: 0.2270381837,
      x1: 0.6357481626,
      y1: 0.7391812865,
    });
  });

  it("clamps coordinates to the normalized page bounds", () => {
    expect(normalizePdfRegionBounds({ x0: -0.2, y0: -0.1, x1: 1.3, y1: 1.2 })).toEqual({
      x0: 0,
      y0: 0,
      x1: 1,
      y1: 1,
    });
  });

  it("orders reversed corners", () => {
    expect(normalizePdfRegionBounds({ x0: 0.8, y0: 0.9, x1: 0.2, y1: 0.1 })).toEqual({
      x0: 0.2,
      y0: 0.1,
      x1: 0.8,
      y1: 0.9,
    });
  });

  it("rejects a rectangle that collapses after quantization", () => {
    expect(normalizePdfRegionBounds({
      x0: 0.1,
      y0: 0.2,
      x1: 0.100000000004,
      y1: 0.8,
    })).toBeNull();
  });

  it("rejects bounds that cannot form a positive quantized rectangle", () => {
    expect(normalizePdfRegionBounds({ x0: Number.NaN, y0: 0.2, x1: 0.8, y1: 0.9 })).toBeNull();
  });
});

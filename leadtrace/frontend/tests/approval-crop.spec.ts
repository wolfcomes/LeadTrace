import { describe, expect, it } from "vitest";
import { cropGeometry, validateCrop } from "../src/approvals/frozenPdf";
describe("frozen PDF region geometry", () => {
  it("clips the exact normalized region with high-density bounded pixels and correct aspect ratio", () => {
    const box = { x0: 0.1, y0: 0.2, x1: 0.5, y1: 0.4 };
    const render = cropGeometry({ width: 600, height: 800 }, box, 400, 2);
    expect(render.width).toBe(800);
    expect(render.height).toBeCloseTo(533, 0);
    expect(render.scale).toBeCloseTo(800 / 240);
    expect(render.offsetX).toBeCloseTo(-200);
    expect(render.offsetY).toBeCloseTo(-533.333);
    const large = cropGeometry({ width: 600, height: 800 }, box, 100000, 4);
    expect(large.width * large.height).toBeLessThanOrEqual(4_000_000);
    expect(Math.max(large.width, large.height)).toBeLessThanOrEqual(4096);
  });
  it("rejects incomplete/inverted/out-of-page regions rather than painting a misleading screenshot", () => {
    expect(validateCrop({ x0: null, y0: 0, x1: 0.2, y1: 1 })).toBeNull();
    expect(validateCrop({ x0: 0.8, y0: 0, x1: 0.2, y1: 1 })).toBeNull();
    expect(validateCrop({ x0: 0, y0: 0, x1: 1.1, y1: 1 })).toBeNull();
  });
});

import { afterEach, vi } from "vitest";
import { createFrozenPdfPool } from "../src/approvals/frozenPdf";
const mocks = vi.hoisted(() => ({
  getDocument: vi.fn(),
  destroy: vi.fn(async () => {}),
}));
vi.mock("pdfjs-dist", () => ({
  GlobalWorkerOptions: {},
  getDocument: mocks.getDocument,
}));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});
describe("approval PDF lifetime and identity", () => {
  it("shares one verified document, rejects changed bytes, and destroys resources on disposal", async () => {
    const fake = { getPage: vi.fn() };
    mocks.getDocument.mockReturnValue({
      promise: Promise.resolve(fake),
      destroy: mocks.destroy,
    });
    const fetch = vi.fn(async () => new Response(new Uint8Array([1, 2, 3])));
    vi.stubGlobal("fetch", fetch);
    vi.stubGlobal("crypto", {
      subtle: { digest: vi.fn(async () => new Uint8Array(32).fill(10).buffer) },
    });
    const pool = createFrozenPdfPool();
    const sha = "0a".repeat(32);
    const docs = await Promise.all([
      pool.document("/source", sha),
      pool.document("/source", sha),
    ]);
    expect(docs[0]).toBe(docs[1]);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(mocks.getDocument).toHaveBeenCalledTimes(1);
    await expect(pool.document("/wrong", "bb".repeat(32))).rejects.toThrow(
      "source-mismatch",
    );
    expect(mocks.getDocument).toHaveBeenCalledTimes(1);
    pool.dispose();
    expect(mocks.destroy).toHaveBeenCalledTimes(1);
    await expect(pool.document("/source", sha)).rejects.toThrow("disposed");
  });
  it("destroys failed PDF parsing workers before allowing retry", async () => {
    mocks.getDocument.mockReturnValue({
      promise: Promise.reject(new Error("bad-pdf")),
      destroy: mocks.destroy,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(new Uint8Array([1]))),
    );
    vi.stubGlobal("crypto", {
      subtle: { digest: vi.fn(async () => new Uint8Array(32).fill(10).buffer) },
    });
    const pool = createFrozenPdfPool();
    await expect(pool.document("/source", "0a".repeat(32))).rejects.toThrow(
      "bad-pdf",
    );
    expect(mocks.destroy).toHaveBeenCalledTimes(1);
    pool.dispose();
    expect(mocks.destroy).toHaveBeenCalledTimes(1);
  });
});

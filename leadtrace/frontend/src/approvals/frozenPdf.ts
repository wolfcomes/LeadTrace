import { inject, onBeforeUnmount, provide, type InjectionKey } from "vue";
import type { PDFDocumentProxy, PDFDocumentLoadingTask } from "pdfjs-dist";
export interface CropBounds {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}
export function validateCrop(
  value: Record<string, unknown>,
): CropBounds | null {
  const keys = ["x0", "y0", "x1", "y1"] as const;
  if (keys.some((k) => value[k] == null || value[k] === "")) return null;
  const [x0, y0, x1, y1] = keys.map((k) => Number(value[k]));
  return [x0, y0, x1, y1].every(
    (x) => Number.isFinite(x) && x >= 0 && x <= 1,
  ) &&
    x1 > x0 &&
    y1 > y0
    ? { x0, y0, x1, y1 }
    : null;
}
export function cropGeometry(
  page: { width: number; height: number },
  box: CropBounds,
  displayWidth: number,
  density: number,
) {
  const w = page.width * (box.x1 - box.x0),
    h = page.height * (box.y1 - box.y0);
  const scale = Math.min(
    (Math.max(1, displayWidth) * Math.max(1, density)) / w,
    4096 / Math.max(w, h),
    Math.sqrt(4_000_000 / (w * h)),
  );
  return {
    scale,
    width: Math.max(1, Math.floor(w * scale)),
    height: Math.max(1, Math.floor(h * scale)),
    offsetX: -box.x0 * page.width * scale,
    offsetY: -box.y0 * page.height * scale,
  };
}
// Pool lifetime is one approval view. Two documents and two active crop renders
// bound memory; leaving that view aborts fetches and destroys PDF workers.
export function createFrozenPdfPool() {
  const entries = new Map<string, Promise<PDFDocumentProxy>>(),
    tasks = new Set<PDFDocumentLoadingTask>(),
    controller = new AbortController();
  let disposed = false,
    active = 0;
  const waiting: (() => void)[] = [];
  async function document(url: string, sha: string): Promise<PDFDocumentProxy> {
    if (disposed) throw new Error("disposed");
    const key = `${url}:${sha}`;
    let promise = entries.get(key);
    if (!promise) {
      if (entries.size >= 2) throw new Error("too-many-sources");
      promise = (async () => {
        const response = await fetch(url, {
          credentials: "same-origin",
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("source-unavailable");
        const bytes = await response.arrayBuffer();
        const actual = [
          ...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
        ]
          .map((x) => x.toString(16).padStart(2, "0"))
          .join("");
        if (actual !== sha) throw new Error("source-mismatch");
        if (disposed) throw new Error("disposed");
        const pdfjs = await import("pdfjs-dist");
        if (disposed) throw new Error("disposed");
        pdfjs.GlobalWorkerOptions.workerSrc = new URL(
          "pdfjs-dist/build/pdf.worker.min.mjs",
          import.meta.url,
        ).toString();
        const task = pdfjs.getDocument({ data: bytes });
        tasks.add(task);
        try {
          return await task.promise;
        } catch (error) {
          tasks.delete(task);
          await task.destroy().catch(() => {});
          throw error;
        }
      })();
      entries.set(key, promise);
      void promise.catch(() => {
        entries.delete(key);
      });
    }
    return promise;
  }
  async function render<T>(job: () => Promise<T>): Promise<T> {
    if (active >= 2)
      await new Promise<void>((resolve) => waiting.push(resolve));
    if (disposed) throw new Error("disposed");
    active++;
    try {
      return await job();
    } finally {
      active--;
      waiting.shift()?.();
    }
  }
  function dispose(): void {
    disposed = true;
    controller.abort();
    for (const task of tasks) void task.destroy().catch(() => {});
    tasks.clear();
    entries.clear();
    waiting.splice(0).forEach((resolve) => resolve());
  }
  return { document, render, dispose };
}
const poolKey: InjectionKey<ReturnType<typeof createFrozenPdfPool>> = Symbol(
  "frozen-approval-pdfs",
);
export function useFrozenPdfPool() {
  const inherited = inject(poolKey, null);
  if (inherited) return inherited;
  const pool = createFrozenPdfPool();
  provide(poolKey, pool);
  onBeforeUnmount(pool.dispose);
  return pool;
}

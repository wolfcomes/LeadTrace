import { mount, flushPromises } from '@vue/test-utils';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import PdfReviewCanvas from '../src/pdf-viewer/PdfReviewCanvas.vue';
const pdf = vi.hoisted(() => ({ getDocument: vi.fn() }));
vi.mock('pdfjs-dist', () => ({ getDocument: pdf.getDocument, GlobalWorkerOptions: {} }));
let width = 800;
let resize: ResizeObserverCallback;
let disconnect: ReturnType<typeof vi.fn>;
const wrappers: ReturnType<typeof mount>[] = [];
beforeEach(() => {
 width = 800;
 vi.stubGlobal('devicePixelRatio', 2);
 vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(function() { return width; });
 vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: vi.fn() } as any);
 disconnect = vi.fn();
 vi.stubGlobal('ResizeObserver', class { constructor(cb: ResizeObserverCallback) { resize = cb; } observe() {} disconnect = disconnect; });
 vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => { cb(0); return 1; });
 vi.stubGlobal('cancelAnimationFrame', vi.fn());
});
afterEach(() => { wrappers.forEach(w => w.unmount()); wrappers.length = 0; vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function open(w = 612, h = 792) {
 const render = vi.fn(() => ({ promise: Promise.resolve(), cancel: vi.fn() }));
 pdf.getDocument.mockReturnValue({ promise: Promise.resolve({ getPage: () => Promise.resolve({
  getViewport: ({ scale }: { scale: number }) => ({ width: w * scale, height: h * scale }), render,
 }) }), destroy: () => Promise.resolve() });
 const wrapper = mount(PdfReviewCanvas, { props: { pdfUrl: '/synthetic.pdf', pageCount: 1, regions: [] } });
 wrappers.push(wrapper); await flushPromises();
 return { wrapper, render, canvas: wrapper.get('canvas').element as HTMLCanvasElement };
}
it('renders enough pixels for actual display width on a high density screen', async () => {
 const { canvas } = await open();
 expect(canvas.width).toBe(1600);
 expect(canvas.height).toBeCloseTo(1600 * 792 / 612, -1);
});
it('adapts to narrower displays and resize without reloading the PDF', async () => {
 width = 320; pdf.getDocument.mockClear();
 const { canvas, render } = await open();
 expect(canvas.width).toBe(640);
 width = 480; resize([], {} as ResizeObserver); await flushPromises();
 expect(canvas.width).toBe(960);
 const count = render.mock.calls.length;
 resize([], {} as ResizeObserver); await flushPromises();
 expect(render).toHaveBeenCalledTimes(count);
 expect(pdf.getDocument).toHaveBeenCalledTimes(1);
});
it('caps both total pixel area and extreme page dimensions even with high zoom', async () => {
 vi.stubGlobal('devicePixelRatio', 4);
 const { wrapper, canvas } = await open(612, 792);
 for (let n = 0; n < 20; n++) await wrapper.get('[aria-label="放大"]').trigger('click');
 await flushPromises();
 expect(canvas.width * canvas.height).toBeLessThanOrEqual(8_000_000);
 expect(canvas.width).toBeGreaterThan(1600);
 expect(canvas.width / canvas.height).toBeCloseTo(612 / 792, 2);
 const extreme = await open(10, 10000);
 expect(extreme.canvas.height).toBeLessThanOrEqual(8192);
});
it('updates for display density changes and disconnects observation on unmount', async () => {
 const { wrapper, canvas } = await open();
 vi.stubGlobal('devicePixelRatio', 1); window.dispatchEvent(new Event('resize')); await flushPromises();
 expect(canvas.width).toBe(800);
 wrapper.unmount(); wrappers.length = 0;
 expect(disconnect).toHaveBeenCalled();
});
it('coalesces queued resizes and cancels the queued callback on unmount', async () => {
 const callbacks = new Map<number, FrameRequestCallback>(); let id = 0;
 vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => { callbacks.set(++id, cb); return id; });
 const cancel = vi.fn((key: number) => callbacks.delete(key));
 vi.stubGlobal('cancelAnimationFrame', cancel);
 const { wrapper, canvas, render } = await open();
 const count = render.mock.calls.length;
 width = 360; resize([], {} as ResizeObserver);
 width = 480; resize([], {} as ResizeObserver);
 expect(callbacks.size).toBe(1); expect(render).toHaveBeenCalledTimes(count);
 const pending = [...callbacks.values()][0]; callbacks.clear(); pending(0); await flushPromises();
 expect(canvas.width).toBe(960);
 width = 600; resize([], {} as ResizeObserver); expect(callbacks.size).toBe(1);
 wrapper.unmount(); wrappers.length = 0;
 expect(callbacks.size).toBe(0); expect(cancel).toHaveBeenCalled();
});

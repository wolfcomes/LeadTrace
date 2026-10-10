// Bound both memory (two RGBA canvases while rendering) and browser canvas size.
const MAX_PIXELS = 8_000_000;
const MAX_DIMENSION = 8192;

export function pdfRenderScale(
  page: { width: number; height: number },
  displayWidth: number,
  devicePixelRatio: number,
  zoom: number,
): number {
  const density = Number.isFinite(devicePixelRatio) && devicePixelRatio > 0 ? devicePixelRatio : 1;
  const width = displayWidth > 0 ? displayWidth : page.width;
  return Math.min(
    width * density * zoom / page.width,
    Math.sqrt(MAX_PIXELS / (page.width * page.height)),
    MAX_DIMENSION / page.width,
    MAX_DIMENSION / page.height,
  );
}

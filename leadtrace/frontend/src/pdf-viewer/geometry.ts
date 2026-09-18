export interface PdfRegionBounds {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

const PDF_REGION_COORDINATE_SCALE = 10 ** 10;

function clamp(value: number): number {
  return Math.min(1, Math.max(0, value));
}

function quantize(value: number): number {
  return Math.round(value * PDF_REGION_COORDINATE_SCALE) / PDF_REGION_COORDINATE_SCALE;
}

export function normalizePdfRegionBounds(bounds: PdfRegionBounds): PdfRegionBounds | null {
  const firstX = clamp(bounds.x0);
  const secondX = clamp(bounds.x1);
  const firstY = clamp(bounds.y0);
  const secondY = clamp(bounds.y1);
  const normalized = {
    x0: quantize(Math.min(firstX, secondX)),
    y0: quantize(Math.min(firstY, secondY)),
    x1: quantize(Math.max(firstX, secondX)),
    y1: quantize(Math.max(firstY, secondY)),
  };

  if (!(normalized.x1 > normalized.x0 && normalized.y1 > normalized.y0)) return null;
  return normalized;
}

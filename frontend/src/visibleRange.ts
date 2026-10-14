// src/visibleRange.ts
// Pure helper for TrendPane: decides which x range to report when the user zooms.
// Kept out of the component so it can be tested without a canvas (uPlot needs matchMedia).

/**
 * Decide the x range reported to onZoom.
 * Uses the plot's own scale when both bounds are set, otherwise the first and last time stamps.
 * Returns null when there is no usable range (no data, or a bound is not a finite number),
 * so the caller can skip reporting instead of sending undefined or NaN.
 */
export function visibleRange(
  scaleMin: number | undefined,
  scaleMax: number | undefined,
  times: ArrayLike<number | null>,
): [number, number] | null {
  const hasScale = scaleMin !== undefined && scaleMax !== undefined;
  const range: [number | null | undefined, number | null | undefined] = hasScale
    ? [scaleMin, scaleMax]
    : [times[0], times[times.length - 1]];
  const [min, max] = range;
  if (typeof min !== "number" || typeof max !== "number") return null;
  if (!Number.isFinite(min) || !Number.isFinite(max)) return null;
  return [min, max];
}

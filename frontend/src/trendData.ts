/**
 * Pure transforms between the API `Series` payload and uPlot-friendly arrays.
 *
 * All functions here are side-effect free: they read their arguments and
 * return new arrays, so they are trivial to unit test without a DOM.
 */

import type { Series } from "./api";

/** Nanoseconds in one second. uPlot expects seconds, the API sends nanoseconds. */
export const NS_PER_SECOND = 1e9;

/** Seconds in one hour, used to translate a range preset into a window. */
const SECONDS_PER_HOUR = 3600;

/** A selectable time window, relative to the end of the series. */
export type RangePreset = "1h" | "8h" | "24h" | "all";

/** How many hours each preset covers. "all" is handled separately (no window). */
const PRESET_HOURS: Record<Exclude<RangePreset, "all">, number> = {
  "1h": 1,
  "8h": 8,
  "24h": 24,
};

/**
 * Turn a finding window (seconds since the first sample) into an x range on the plot's time axis.
 *
 * @param timeAxis Column 0 of the uPlot data, in seconds.
 * @returns `[min, max]` on the same axis, or null when there is no window or no data.
 */
export function windowToRange(
  timeAxis: readonly (number | null)[],
  window: readonly [number, number] | undefined,
): [number, number] | null {
  const first = timeAxis.length > 0 ? timeAxis[0] : null;
  if (window === undefined || first === null) {
    return null;
  }
  return [first + window[0], first + window[1]];
}

/**
 * Convert a list of series into the column layout uPlot wants.
 *
 * Column 0 is the shared time axis in SECONDS (converted from nanoseconds);
 * columns 1..n are the `mean` arrays of each series, in the given order.
 *
 * @returns A column-oriented array: `[timesInSeconds, mean0, mean1, ...]`.
 * @throws RangeError If the series do not all share the same time axis length.
 */
export function toUplotData(series: readonly Series[]): (number | null)[][] {
  if (series.length === 0) {
    return [[]];
  }

  const timeAxis = secondsFromNanoseconds(series[0].t);
  for (const oneSeries of series) {
    if (oneSeries.t.length !== timeAxis.length) {
      throw new RangeError("series have different time axes");
    }
  }

  return [timeAxis, ...series.map((oneSeries) => [...oneSeries.mean])];
}

/**
 * Extract the min/max envelope of a single series.
 *
 * @returns `lower` is the `min` array, `upper` is the `max` array.
 */
export function toEnvelope(series: Series): { lower: (number | null)[]; upper: (number | null)[] } {
  return { lower: [...series.min], upper: [...series.max] };
}

/**
 * Report whether at least one series has been downsampled by the server.
 *
 * The UI uses this to warn that the chart shows fewer points than were recorded.
 *
 * @returns True as soon as one series is flagged; false for an empty list.
 */
export function anyDownsampled(series: readonly Series[]): boolean {
  return series.some((oneSeries) => oneSeries.downsampled);
}

/**
 * Translate a range preset into a nanosecond window ending at the last sample.
 *
 * @param seriesEndSeconds End of the series, in seconds since the Unix epoch.
 * @param preset Window size; "all" means "no window".
 * @returns `{}` for "all", otherwise the inclusive start and end in nanoseconds.
 */
export function rangeToNs(
  seriesEndSeconds: number,
  preset: RangePreset,
): { startNs?: number; endNs?: number } {
  if (preset === "all") {
    return {};
  }

  const endNs = seriesEndSeconds * NS_PER_SECOND;
  const windowNs = PRESET_HOURS[preset] * SECONDS_PER_HOUR * NS_PER_SECOND;
  return { startNs: endNs - windowNs, endNs };
}

/**
 * Find the index of the sample time closest to `x`.
 *
 * `times` must be sorted ascending. Uses binary search, so it stays fast on
 * the tens of thousands of points a long window can hold.
 *
 * @returns The closest index, or -1 when `times` is empty.
 */
export function nearestIndex(times: readonly number[], x: number): number {
  if (times.length === 0) {
    return -1;
  }

  let low = 0;
  let high = times.length - 1;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (times[middle] < x) {
      low = middle + 1;
    } else {
      high = middle;
    }
  }

  return closestOf(times, low, x);
}

/**
 * Convert an array of nanosecond timestamps to seconds.
 *
 * @returns A new array, so the caller cannot mutate the series payload.
 */
function secondsFromNanoseconds(nanoseconds: readonly number[]): number[] {
  return nanoseconds.map((value) => value / NS_PER_SECOND);
}

/**
 * Pick, between the insertion point and its left neighbour, the nearer index.
 *
 * @param insertionIndex Index of the first time >= x (binary search result).
 * @returns The index whose time is closest to x.
 */
function closestOf(times: readonly number[], insertionIndex: number, x: number): number {
  if (insertionIndex === 0) {
    return 0;
  }

  const leftDistance = Math.abs(x - times[insertionIndex - 1]);
  const rightDistance = Math.abs(times[insertionIndex] - x);
  return rightDistance < leftDistance ? insertionIndex : insertionIndex - 1;
}

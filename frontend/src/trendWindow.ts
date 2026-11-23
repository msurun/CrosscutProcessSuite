/**
 * Pure transforms between the Trends time window and the API Series payload.
 *
 * All functions here are side-effect free: they read their arguments and
 * return new objects, so they are trivial to unit test without a DOM.
 */

/** Nanoseconds in one second. */
export const NS_PER_SECOND = 1e9;
/** Nanoseconds per millisecond (Date.parse and Date.now work in ms). */
export const NS_PER_MS = 1e6;

/** Milliseconds in one second. */
export const MS_PER_SECOND = 1000;

/** One time window of the Trends view. */
export type TrendWindow =
  | { kind: "relative"; last_s: number; live?: boolean; refresh_s?: number }
  | { kind: "absolute"; start_utc: string; end_utc: string };

/** Time window presets in seconds. */
export const WIDTH_PRESETS_S: readonly { id: string; seconds: number }[] = [
  { id: "15m", seconds: 900 },
  { id: "1h", seconds: 3600 },
  { id: "8h", seconds: 28800 },
  { id: "24h", seconds: 86400 },
  { id: "7d", seconds: 604800 },
  { id: "30d", seconds: 2592000 },
];

/**
 * Resolve a window to nanosecond timestamps.
 *
 * @param w The window to resolve.
 * @param nowMs Current time in milliseconds since the Unix epoch.
 * @param dataEndNs Optional end of the data in nanoseconds.
 * @returns The resolved window with start and end in nanoseconds.
 */
export function resolveWindow(
  w: TrendWindow,
  nowMs: number,
  dataEndNs?: number,
): { startNs: number; endNs: number } {
  if (w.kind === "relative") {
    const endNs = dataEndNs ?? nowMs * NS_PER_MS;
    const startNs = endNs - w.last_s * NS_PER_SECOND;
    return { startNs, endNs };
  } else {
    const startMs = Date.parse(w.start_utc);
    const endMs = Date.parse(w.end_utc);
    return { startNs: startMs * NS_PER_MS, endNs: endMs * NS_PER_MS };
  }
}

/**
 * Pan a window by one window width.
 *
 * @param w The window to pan.
 * @param direction The direction to pan (-1 for left, 1 for right).
 * @param nowMs Current time in milliseconds since the Unix epoch.
 * @param dataEndNs Optional end of the data in nanoseconds.
 * @returns The panned window.
 */
export function panWindow(
  w: TrendWindow,
  direction: -1 | 1,
  nowMs: number,
  dataEndNs?: number,
): TrendWindow {
  const { startNs, endNs } = resolveWindow(w, nowMs, dataEndNs);
  const widthNs = endNs - startNs;
  const newStartNs = startNs + direction * widthNs;
  const newEndNs = endNs + direction * widthNs;

  if (w.kind === "relative") {
    return { kind: "relative", last_s: w.last_s, live: w.live, refresh_s: w.refresh_s };
  } else {
    return {
      kind: "absolute",
      start_utc: new Date(newStartNs / NS_PER_MS).toISOString(),
      end_utc: new Date(newEndNs / NS_PER_MS).toISOString(),
    };
  }
}

/**
 * Set the width of a window.
 *
 * @param w The window to set the width of.
 * @param seconds The width in seconds.
 * @param nowMs Current time in milliseconds since the Unix epoch.
 * @param dataEndNs Optional end of the data in nanoseconds.
 * @returns The window with the new width.
 */
export function withWidth(
  w: TrendWindow,
  seconds: number,
  nowMs: number,
  dataEndNs?: number,
): TrendWindow {
  if (w.kind === "relative") {
    return { kind: "relative", last_s: seconds, live: w.live, refresh_s: w.refresh_s };
  } else {
    const { endNs } = resolveWindow(w, nowMs, dataEndNs);
    const startNs = endNs - seconds * NS_PER_SECOND;
    return {
      kind: "absolute",
      start_utc: new Date(startNs / NS_PER_MS).toISOString(),
      end_utc: new Date(endNs / NS_PER_MS).toISOString(),
    };
  }
}

/**
 * Check if a window is live.
 *
 * @param w The window to check.
 * @returns True if the window is live, false otherwise.
 */
export function isLive(w: TrendWindow): boolean {
  return w.kind === "relative" && w.live === true;
}

/**
 * Validate a window.
 *
 * @param w The window to validate.
 * @returns An array of error messages, empty if the window is valid.
 */
export function validateWindow(w: TrendWindow): string[] {
  const errors: string[] = [];

  if (w.kind === "relative") {
    if (w.last_s < 60) {
      errors.push("Relative window must be at least 60 seconds.");
    }
  } else {
    const startMs = Date.parse(w.start_utc);
    const endMs = Date.parse(w.end_utc);

    if (isNaN(startMs)) {
      errors.push("Invalid start time.");
    }

    if (isNaN(endMs)) {
      errors.push("Invalid end time.");
    }

    if (!isNaN(startMs) && !isNaN(endMs) && endMs <= startMs) {
      errors.push("End time must be after start time.");
    }
  }

  return errors;
}


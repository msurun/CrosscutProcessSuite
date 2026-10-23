// Pure helpers of the Anomalies page: window validation in hours, event table rows, the shading
// mask for the charts, contribution ranking and the mapping of API errors to message codes.
// No React, so they are unit-tested alone. All times from the API are seconds from the record start.
import { ApiError, type AnomalyEvent } from "./api";

const SECONDS_PER_HOUR = 3600;
/** Longest default training window, in hours. */
const MAX_DEFAULT_TRAIN_HOURS = 24;
/** Value of the shading mask outside events (any value except 0, which is drawn as a band). */
const MASK_QUIET = 1;
const MASK_EVENT = 0;
/** How many tags the contribution bars show. */
export const TOP_TAGS = 5;

/** Why a window typed in hours is not acceptable (the string is the `anomaly.window.<code>` key part). */
export type WindowError = "notNumber" | "negative" | "order" | "beyond";

/** A checked window: seconds on success, otherwise the first problem found. */
export type WindowCheck = { ok: true; startS: number; endS: number } | { ok: false; error: WindowError };

/** Default "use first N hours": half of the record, at most 24 h, in steps of 0.5 h (at least 0.5; the whole hours of the record are halved). */
export function defaultTrainHours(hours: number | null): number {
  if (hours === null || !(hours > 0)) return 1;
  const half = Math.floor(hours) / 2;
  return Math.min(MAX_DEFAULT_TRAIN_HOURS, Math.max(0.5, half));
}

/** Parses a decimal number typed by the user (comma or dot); null when it is not a finite number. */
export function parseHours(text: string): number | null {
  const trimmed = text.trim().replace(",", ".");
  if (trimmed === "") return null;
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
}

/** Checks a start and end (hours from the record start) against the record length (hours, or null if unknown). */
export function validateWindow(startText: string, endText: string, recordHours: number | null): WindowCheck {
  const start = parseHours(startText);
  const end = parseHours(endText);
  if (start === null || end === null) return { ok: false, error: "notNumber" };
  if (start < 0 || end < 0) return { ok: false, error: "negative" };
  if (end <= start) return { ok: false, error: "order" };
  if (recordHours !== null && start >= recordHours) return { ok: false, error: "beyond" };
  return { ok: true, startS: start * SECONDS_PER_HOUR, endS: end * SECONDS_PER_HOUR };
}

/** What the API error means for the user, when it is one of the known cases. */
export type AnomalyErrorCode = "notFitted" | "stale" | "unknownTag" | "badTag";

/** Classifies an API error by status and message (the API sends no machine codes for these); null if unknown. */
export function anomalyErrorCode(error: unknown): AnomalyErrorCode | null {
  if (!(error instanceof ApiError)) return null;
  const message = error.message.toLowerCase();
  if (error.status === 404 && message.includes("model not fitted")) return "notFitted";
  if (error.status === 422 && message.includes("model is stale")) return "stale";
  if (message.includes("unknown tags")) return "unknownTag";
  return null;
}

/** One row of the events table. Ratios are the peak statistic divided by its limit (above 1 = over the limit). */
export interface EventRow {
  index: number;
  startS: number;
  endS: number;
  durationS: number;
  t2Ratio: number;
  speRatio: number;
  exceeded: AnomalyEvent["exceeded"];
  closed: boolean;
}

/** Table rows of the events of a scan, in time order. */
export function eventRows(events: readonly AnomalyEvent[], t2Limit: number, speLimit: number): EventRow[] {
  return events.map((event, index) => ({
    index,
    startS: event.start_s,
    endS: event.end_s,
    durationS: event.end_s - event.start_s,
    t2Ratio: event.peak_t2 / t2Limit,
    speRatio: event.peak_spe / speLimit,
    exceeded: event.exceeded,
    closed: event.closed,
  }));
}

/** Shading mask for the charts: 0 (drawn as a band) while an event is open at that time, 1 elsewhere. */
export function eventMask(timesS: readonly number[], events: readonly AnomalyEvent[]): number[] {
  return timesS.map((time) => (events.some((event) => time >= event.start_s && time <= event.end_s) ? MASK_EVENT : MASK_QUIET));
}

/** The largest `count` shares of a tag-to-share map, biggest first. */
export function topShares(shares: Record<string, number>, count = TOP_TAGS): [string, number][] {
  return Object.entries(shares).sort((a, b) => b[1] - a[1]).slice(0, count);
}

/** Hours from seconds, for axes and tables. */
export function toHours(seconds: number): number {
  return seconds / SECONDS_PER_HOUR;
}

/** Record length in hours from the ISO start and end of a dataset; null when it cannot be read. */
export function recordHours(startUtc: string, endUtc: string): number | null {
  const span = (Date.parse(endUtc) - Date.parse(startUtc)) / (1000 * SECONDS_PER_HOUR);
  return Number.isFinite(span) && span > 0 ? span : null;
}

/** First eight characters of a hash, for display. */
export function shortHash(hash: string): string {
  return hash.slice(0, 8);
}

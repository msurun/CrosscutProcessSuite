// src/tuningIpdt.ts
// Pure helpers of the integrating (level loop) branch of the tuning page: model type guard,
// validation of the averaging-level inputs, alignment of the fitted ramp to a trend axis and
// the locale keys of the refusal reasons. No React, no DOM.

import type { FitCurve, IpdtModel, TuningModel, TuningWarning } from "./api";

/** Reason codes the backend gives for a refused or low-confidence integrating fit. */
export const KNOWN_IPDT_REASONS: readonly string[] = [
  "r2_below_0.8",
  "pre_move_lead_under_20pct",
  "post_move_too_short",
  "theta_on_grid_edge",
  "no_out_move",
  "slope_se_over_20pct",
  "up_down_differ_over_25pct",
];

/** True when the model is the integrator-with-dead-time kind. */
export function isIpdtModel(model: TuningModel | null): model is IpdtModel {
  return model !== null && model.kind === "ipdt";
}

/** Result of validating the two averaging-level fields. */
export type SwingInput =
  | { state: "empty" }
  | { state: "valid"; maxSwing: number; loadStepPct: number }
  | { state: "invalid"; error: "both" | "positive" };

/** Parses a typed number (decimal comma allowed); null for empty or non-numeric text. */
export function parsePositiveCandidate(text: string): number | null {
  const normalized = text.trim().replace(",", ".");
  if (normalized === "") return null;
  const value = Number(normalized);
  return Number.isFinite(value) ? value : null;
}

/** Both fields or none; when given, both must be numbers above zero. */
export function parseSwing(maxSwingText: string, loadStepText: string): SwingInput {
  const swing = parsePositiveCandidate(maxSwingText);
  const load = parsePositiveCandidate(loadStepText);
  const blank = maxSwingText.trim() === "" && loadStepText.trim() === "";
  if (blank) return { state: "empty" };
  if (maxSwingText.trim() === "" || loadStepText.trim() === "") return { state: "invalid", error: "both" };
  if (swing === null || load === null || swing <= 0 || load <= 0) {
    return { state: "invalid", error: "positive" };
  }
  return { state: "valid", maxSwing: swing, loadStepPct: load };
}

/**
 * The fitted ramp on the time axis of a trend pane.
 *
 * `times` are epoch seconds, `firstS` the epoch second of the record's first sample (the curve is in
 * seconds since it). Values are linearly interpolated; outside the curve (or in a gap) they are null.
 */
export function alignCurve(times: readonly (number | null)[], firstS: number, curve: FitCurve): (number | null)[] {
  const last = curve.t_s.length - 1;
  let at = 0;
  return times.map((time) => {
    if (time === null || last < 1) return null;
    const rel = time - firstS;
    if (rel < curve.t_s[0] || rel > curve.t_s[last]) return null;
    while (at < last - 1 && curve.t_s[at + 1] < rel) at += 1;
    return interpolate(curve, at, rel);
  });
}

/** Linear value of the curve at `rel` inside segment `at`..`at+1`; null when an end is a gap. */
function interpolate(curve: FitCurve, at: number, rel: number): number | null {
  const [y0, y1] = [curve.pv_model[at], curve.pv_model[at + 1]];
  if (y0 === null || y1 === null) return null;
  const span = curve.t_s[at + 1] - curve.t_s[at];
  return span <= 0 ? y0 : y0 + ((y1 - y0) * (rel - curve.t_s[at])) / span;
}

/** Ratio of upper to lower dead-time bound above which the range counts as wide. */
export const WIDE_DELAY_RATIO = 3;
/** Share of the record length (window span) the range may span before it counts as wide. */
export const WIDE_DELAY_SPAN_SHARE = 0.2;

/**
 * True when the dead-time range is wide: upper/lower above 3, or upper minus lower above 20 % of
 * the record length (the window span in seconds, an upper estimate of the time after the move).
 */
export function isWideDelayRange(model: IpdtModel, spanS: number): boolean {
  const { delay_lower_s: lower, delay_upper_s: upper } = model;
  const ratioWide = lower > 0 ? upper / lower > WIDE_DELAY_RATIO : upper > 0;
  return ratioWide || upper - lower > WIDE_DELAY_SPAN_SHARE * spanS;
}

/** Locale key of the plain-language reason text; unknown codes get the generic text. */
export function reasonKey(code: string): string {
  return KNOWN_IPDT_REASONS.includes(code) ? `tuning.ipdt.reason.${code}` : "tuning.ipdt.reason.unknown";
}

/** Locale key of the "what to do" text for a reason code. */
export function reasonActionKey(code: string): string {
  return KNOWN_IPDT_REASONS.includes(code) ? `tuning.ipdt.action.${code}` : "tuning.ipdt.action.unknown";
}

/** The warning with the given code, if the payload has one. */
export function findWarning<C extends TuningWarning["code"]>(
  warnings: TuningWarning[],
  code: C,
): Extract<TuningWarning, { code: C }> | undefined {
  return warnings.find((warning) => warning.code === code) as Extract<TuningWarning, { code: C }> | undefined;
}

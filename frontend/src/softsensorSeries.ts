// Pure series maths of the Soft sensor page: the carry-forward baseline (last lab value available
// at each time), the lab points snapped to the series times, the shading masks and the RMSE of the
// estimate against the lab values at the lab times. All times are seconds from the record start.
import type { LabRow, SoftSensorSeries } from "./api";
import { UNRELIABLE } from "./softsensor";

const MASK_SHADED = 0;
const MASK_QUIET = 1;

/** Index of the last series time that is at or before `timeS` (-1 when there is none). */
function floorIndex(timesS: readonly number[], timeS: number): number {
  let low = 0;
  let high = timesS.length - 1;
  let found = -1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (timesS[mid] <= timeS) {
      found = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return found;
}

/** Median step of the series times (0 for fewer than two points). */
function typicalStep(timesS: readonly number[]): number {
  if (timesS.length < 2) return 0;
  const steps = timesS.slice(1).map((time, index) => time - timesS[index]).sort((a, b) => a - b);
  return steps[steps.length >> 1];
}

/** Last lab value that was available (sample time + delay) at `timeS`, or null before the first. */
export function carryForwardAt(labs: readonly LabRow[], delayS: number, timeS: number): number | null {
  let value: number | null = null;
  for (const lab of labs) {
    if (lab.t_s + delayS <= timeS) value = lab.value;
  }
  return value;
}

/** The carry-forward baseline on the series times: what the operator has today. */
export function carryForwardSeries(timesS: readonly number[], labs: readonly LabRow[], delayS: number): (number | null)[] {
  return timesS.map((time) => carryForwardAt(labs, delayS, time));
}

/** Lab values on the series times (null elsewhere): each lab sits on the last series time at or before its sample time. */
export function labMarkers(timesS: readonly number[], labs: readonly LabRow[]): (number | null)[] {
  const markers: (number | null)[] = timesS.map(() => null);
  const step = typicalStep(timesS);
  for (const lab of labs) {
    const index = floorIndex(timesS, lab.t_s);
    if (index >= 0 && lab.t_s - timesS[index] < step) markers[index] = lab.value;
  }
  return markers;
}

/** Shading mask: 0 (a band) where the estimate is out of range or extrapolating, 1 elsewhere. */
export function unreliableMask(series: Pick<SoftSensorSeries, "validity">): number[] {
  return series.validity.map((kind) => (UNRELIABLE.includes(kind) ? MASK_SHADED : MASK_QUIET));
}

/** Shading mask: 0 where the drift flag is raised, 1 elsewhere. */
export function driftMask(series: Pick<SoftSensorSeries, "drift">): number[] {
  return series.drift.map((raised) => (raised ? MASK_SHADED : MASK_QUIET));
}

/** RMSE of the estimate, the bias-corrected estimate and the carry-forward baseline over some lab points. */
export interface LabScore {
  n: number;
  estimate: number | null;
  corrected: number | null;
  baseline: number | null;
}

function rmse(errors: readonly number[]): number | null {
  return errors.length === 0 ? null : Math.sqrt(errors.reduce((sum, e) => sum + e * e, 0) / errors.length);
}

/**
 * Scores the series against the lab values at the lab times, on the lab points from `fromS` on
 * (use the train end for the part the model did not see). Only points where the estimate and the
 * baseline both exist are used, so the numbers are comparable; the corrected estimate is scored on
 * those of them where it exists. The baseline of a lab point is the last result that was available
 * before that point's sample time.
 */
export function scoreAgainstLabs(
  series: Pick<SoftSensorSeries, "t_s" | "estimate" | "corrected">,
  labs: readonly LabRow[],
  delayS: number,
  fromS: number,
): LabScore {
  const own: number[] = [];
  const corrected: number[] = [];
  const baseline: number[] = [];
  const endS = (series.t_s.at(-1) ?? 0) + typicalStep(series.t_s);
  for (const lab of labs) {
    if (lab.t_s >= endS) continue;
    const index = floorIndex(series.t_s, lab.t_s);
    const estimate = index >= 0 ? series.estimate[index] : null;
    const last = carryForwardAt(labs.filter((other) => other.t_s < lab.t_s), delayS, lab.t_s);
    if (lab.t_s < fromS || estimate === null || last === null) continue;
    own.push(estimate - lab.value);
    baseline.push(last - lab.value);
    const fixed = series.corrected[index];
    if (fixed !== null) corrected.push(fixed - lab.value);
  }
  return { n: own.length, estimate: rmse(own), corrected: rmse(corrected), baseline: rmse(baseline) };
}

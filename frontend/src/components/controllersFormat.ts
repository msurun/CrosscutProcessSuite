// frontend/src/components/controllersFormat.ts
// Small display helpers of the Controllers view: state chip level, time and age text.

import type { Translate } from "../findings";
import type { ControllerState } from "../controllersApi";
import type { StatusLevel } from "./StatusChip";

const STATE_LEVEL: Record<ControllerState, StatusLevel> = {
  on: "ok",
  standby: "warning",
  shed: "problem",
  off: "unused",
};

/** The chip level of a controller state; an unknown state stays neutral. */
export function stateLevel(state: string): StatusLevel {
  return STATE_LEVEL[state as ControllerState] ?? "unused";
}

/** The chip level of a variable status (good / uncertain / bad / not yet known). */
export function statusLevel(status: string | null): StatusLevel {
  if (status === "good") return "ok";
  if (status === "uncertain") return "warning";
  return status === "bad" ? "problem" : "not_assessed";
}

/** Translates a reason code; a code without text is shown as it is. */
export function reasonText(t: Translate, code: string): string {
  const key = `controllers.reason.${code}`;
  const text = t(key);
  return text === key ? code : text;
}

/** "HH:MM:SSZ" (UTC) of an ISO time, or the placeholder when there is none. */
export function clockText(iso: string | null, none: string): string {
  const parsed = iso === null ? NaN : Date.parse(iso);
  return Number.isNaN(parsed) ? none : `${new Date(parsed).toISOString().slice(11, 19)}Z`;
}

/** Seconds since an ISO time, or null when there is none. */
export function ageSeconds(iso: string | null, nowMs: number): number | null {
  const parsed = iso === null ? NaN : Date.parse(iso);
  return Number.isNaN(parsed) ? null : Math.max(0, Math.round((nowMs - parsed) / 1000));
}

/** True when the host's liveness is older than two cycles (or was never seen). */
export function isStale(liveness: string | null, cycleS: number, nowMs: number): boolean {
  const age = ageSeconds(liveness, nowMs);
  return age === null || age > 2 * cycleS;
}

/** A number for the table; null is the placeholder. */
export function numberText(value: number | null | undefined, none: string): string {
  return value === null || value === undefined ? none : String(Math.round(value * 1000) / 1000);
}

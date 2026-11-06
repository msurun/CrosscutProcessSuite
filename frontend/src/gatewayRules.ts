// frontend/src/gatewayRules.ts
// Mode-transition rules of the Write Gateway for the UI (ADR 013): which targets the current
// session may select. The gateway re-checks everything; this only explains disabled controls.

import type { CanResult } from "./AuthContext";

/** Operating modes from the most restrictive to the most autonomous. */
export const MODE_ORDER: readonly string[] = ["off", "advisory", "dry_run", "confirm", "supervised"];

/** The mode that needs a password re-entry (step-up) to be selected. */
export const STEP_UP_MODE = "supervised";

/** Reason key shown when a jump of more than one step up is attempted. */
export const ONE_STEP_REASON = "gateway.reason.oneStep";

/**
 * Whether the session may move the gateway from `current` to `target`.
 * Down: any jump with `gw.mode.down`. Up: exactly one step with `gw.mode.up.<target>`.
 */
export function modeTransition(
  current: string,
  target: string,
  check: (permission: string) => CanResult,
): CanResult {
  const from = MODE_ORDER.indexOf(current);
  const to = MODE_ORDER.indexOf(target);
  if (from === to || to < 0) return { allowed: true, reason: "" };
  if (from < 0 || to < from) return check("gw.mode.down");
  if (to === from + 1) return check(`gw.mode.up.${target}`);
  return { allowed: false, reason: ONE_STEP_REASON };
}

/** The permission that re-enables a target in `state`, or null when it cannot be re-enabled. */
export function reEnablePermission(state: string): string | null {
  if (state.startsWith("stopped:")) return "gw.re_enable.stopped";
  if (state === "hold_off") return "gw.re_enable.hold_off";
  return null;
}

// frontend/src/gatewayRules.test.ts
// Tests for the gateway mode-transition rules and the re-enable permission by target state.

import { describe, expect, it } from "vitest";
import type { CanResult } from "./AuthContext";
import { MODE_ORDER, ONE_STEP_REASON, modeTransition, reEnablePermission } from "./gatewayRules";

const ROLE_PERMS: Record<string, string[]> = {
  viewer: ["gw.mode.down"],
  engineer: ["gw.mode.down", "gw.mode.up.advisory", "gw.mode.up.dry_run", "gw.mode.up.confirm"],
  lead: ["gw.mode.down", "gw.mode.up.advisory", "gw.mode.up.dry_run", "gw.mode.up.confirm", "gw.mode.up.supervised"],
};

function checker(role: string) {
  return (permission: string): CanResult =>
    ROLE_PERMS[role].includes(permission)
      ? { allowed: true, reason: "" }
      : { allowed: false, reason: "auth.reason.requires_role", requiredRole: "x" };
}

describe("modeTransition", () => {
  it("allows staying on the current mode", () => {
    expect(modeTransition("confirm", "confirm", checker("viewer")).allowed).toBe(true);
  });

  it("allows any jump down with gw.mode.down", () => {
    for (const target of ["off", "advisory", "dry_run"]) {
      expect(modeTransition("supervised", target, checker("viewer")).allowed).toBe(true);
    }
  });

  it("needs gw.mode.up.<mode> for one step up", () => {
    expect(modeTransition("off", "advisory", checker("viewer")).allowed).toBe(false);
    expect(modeTransition("off", "advisory", checker("engineer")).allowed).toBe(true);
    expect(modeTransition("confirm", "supervised", checker("engineer")).allowed).toBe(false);
    expect(modeTransition("confirm", "supervised", checker("lead")).allowed).toBe(true);
  });

  it("refuses a jump of more than one step up for everybody", () => {
    const result = modeTransition("off", "confirm", checker("lead"));
    expect(result).toEqual({ allowed: false, reason: ONE_STEP_REASON });
    expect(modeTransition("advisory", "supervised", checker("lead")).allowed).toBe(false);
  });

  it("treats every mode name in MODE_ORDER as known", () => {
    expect(MODE_ORDER).toHaveLength(5);
  });
});

describe("reEnablePermission", () => {
  it("maps target states to permissions", () => {
    expect(reEnablePermission("stopped:kill")).toBe("gw.re_enable.stopped");
    expect(reEnablePermission("hold_off")).toBe("gw.re_enable.hold_off");
    expect(reEnablePermission("enabled")).toBeNull();
  });
});

// src/tuningIpdt.test.ts
// Tests of the pure helpers of the integrating-loop branch: swing validation, curve alignment,
// reason keys and the model type guard.

import { describe, expect, it } from "vitest";

import type { IpdtModel } from "./api";
import { alignCurve, findWarning, isIpdtModel, isWideDelayRange, parseSwing, reasonActionKey, reasonKey } from "./tuningIpdt";

describe("parseSwing", () => {
  it("treats two empty fields as not used", () => {
    expect(parseSwing("", "  ")).toEqual({ state: "empty" });
  });

  it("accepts two positive numbers, with a decimal comma", () => {
    expect(parseSwing("2,5", "4")).toEqual({ state: "valid", maxSwing: 2.5, loadStepPct: 4 });
  });

  it("asks for both values when only one is given", () => {
    expect(parseSwing("2", "")).toEqual({ state: "invalid", error: "both" });
    expect(parseSwing("", "3")).toEqual({ state: "invalid", error: "both" });
  });

  it("rejects zero, negative and non-numeric values", () => {
    expect(parseSwing("0", "3")).toEqual({ state: "invalid", error: "positive" });
    expect(parseSwing("2", "-1")).toEqual({ state: "invalid", error: "positive" });
    expect(parseSwing("abc", "3")).toEqual({ state: "invalid", error: "positive" });
  });
});

describe("alignCurve", () => {
  const curve = { t_s: [10, 20, 30], pv_model: [1, 3, null] };

  it("interpolates inside the curve and gives null outside it", () => {
    const times = [1000, 1010, 1015, 1020, 1100];
    expect(alignCurve(times, 1000, curve)).toEqual([null, 1, 2, 3, null]);
  });

  it("gives null where the curve has a gap and for null times", () => {
    expect(alignCurve([1025, null], 1000, curve)).toEqual([null, null]);
  });

  it("gives all null for a curve with fewer than two points", () => {
    expect(alignCurve([1010], 1000, { t_s: [10], pv_model: [1] })).toEqual([null]);
  });
});

describe("reason keys and guards", () => {
  it("maps known reasons to their own keys and unknown ones to the generic key", () => {
    expect(reasonKey("no_out_move")).toBe("tuning.ipdt.reason.no_out_move");
    expect(reasonActionKey("post_move_too_short")).toBe("tuning.ipdt.action.post_move_too_short");
    expect(reasonKey("something_new")).toBe("tuning.ipdt.reason.unknown");
    expect(reasonActionKey("something_new")).toBe("tuning.ipdt.action.unknown");
  });

  it("tells the model kinds apart", () => {
    expect(isIpdtModel(null)).toBe(false);
    expect(isIpdtModel({ kind: "fopdt", gain: 1, time_constant_s: 1, delay_s: 1 })).toBe(false);
  });

  it("finds a warning by code", () => {
    const warnings = [{ code: "closed_loop_data" as const }];
    expect(findWarning(warnings, "closed_loop_data")).toEqual({ code: "closed_loop_data" });
    expect(findWarning(warnings, "looks_self_regulating")).toBeUndefined();
  });
});

describe("isWideDelayRange", () => {
  const model = (lower: number, upper: number): IpdtModel => ({
    kind: "ipdt",
    slope_per_s: 0.01,
    delay_s: lower,
    delay_lower_s: lower,
    delay_upper_s: upper,
    delay_used_s: upper,
    r_squared: 0.9,
    slope_rel_se: null,
    up_down_ratio: null,
    baseline_slope: 0,
    verdict: "ok",
    reasons: [],
  });

  it("is narrow for a small ratio and a small share of the record", () => {
    expect(isWideDelayRange(model(10, 20), 1000)).toBe(false);
  });

  it("is wide when upper/lower exceeds 3", () => {
    expect(isWideDelayRange(model(3, 12), 10000)).toBe(true);
    expect(isWideDelayRange(model(5, 15), 10000)).toBe(false);
  });

  it("is wide when the range exceeds 20 % of the record", () => {
    expect(isWideDelayRange(model(100, 250), 700)).toBe(true);
    expect(isWideDelayRange(model(100, 250), 800)).toBe(false);
  });
});

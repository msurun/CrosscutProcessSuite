// Unit tests of the pure Soft sensor helpers: train-end check, lab text check, API error codes,
// the carry-forward baseline, the lab markers, the shading masks and the RMSE against the labs.
import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import { checkLabText, defaultTrainEndHours, percentOf, softErrorCode, validateTrainEnd } from "./softsensor";
import { carryForwardAt, carryForwardSeries, driftMask, labMarkers, scoreAgainstLabs, unreliableMask } from "./softsensorSeries";

describe("train end", () => {
  it("defaults to three quarters of the record in half hours", () => {
    expect(defaultTrainEndHours(6)).toBe(4.5);
    expect(defaultTrainEndHours(1)).toBe(0.5);
    expect(defaultTrainEndHours(null)).toBe(1);
  });

  it("accepts hours with a comma and converts to seconds", () => {
    expect(validateTrainEnd("4,5", 6)).toEqual({ ok: true, endS: 16200 });
  });

  it("names the problem", () => {
    expect(validateTrainEnd("abc", 6)).toEqual({ ok: false, error: "notNumber" });
    expect(validateTrainEnd("0", 6)).toEqual({ ok: false, error: "notPositive" });
    expect(validateTrainEnd("7", 6)).toEqual({ ok: false, error: "beyond" });
    expect(validateTrainEnd("7", null)).toEqual({ ok: true, endS: 25200 });
  });
});

describe("lab text check", () => {
  it("rejects empty text and a header without the columns", () => {
    expect(checkLabText("  \n ")).toBe("empty");
    expect(checkLabText("time,val\n1,2")).toBe("columns");
  });

  it("accepts comma, semicolon and tab headers, in any case and with a byte order mark", () => {
    expect(checkLabText("sample_time,value\n0,1")).toBeNull();
    expect(checkLabText("Sample_Time;Value\n0;1")).toBeNull();
    expect(checkLabText("﻿value\tsample_time\n1\t0")).toBeNull();
  });
});

describe("error codes", () => {
  it("classifies the known API messages", () => {
    expect(softErrorCode(new ApiError(404, "model not fitted: s1"))).toBe("notFitted");
    expect(softErrorCode(new ApiError(404, "no lab results uploaded: s1"))).toBe("noLab");
    expect(softErrorCode(new ApiError(422, "input_tags: model is stale, fit it again"))).toBe("stale");
    expect(softErrorCode(new ApiError(422, "unknown tags: ['x.y']"))).toBe("unknownTag");
    expect(softErrorCode(new ApiError(422, "line 3: bad value 'x'"))).toBe("labCsv");
    expect(softErrorCode(new ApiError(422, "csv_text: columns sample_time and value"))).toBe("labCsv");
    expect(softErrorCode(new ApiError(422, "too few valid rows: 3 < 10"))).toBe("fitData");
    expect(softErrorCode(new ApiError(500, "boom"))).toBeNull();
    expect(softErrorCode(new Error("model not fitted"))).toBeNull();
  });

  it("computes percentages safely", () => {
    expect(percentOf(1, 4)).toBe(25);
    expect(percentOf(1, 0)).toBe(0);
  });
});

const LABS = [
  { t_s: 0, value: 10 },
  { t_s: 120, value: 12 },
  { t_s: 240, value: 14 },
];

describe("series maths", () => {
  it("carries the last available lab value forward", () => {
    expect(carryForwardAt(LABS, 60, 30)).toBeNull();
    expect(carryForwardAt(LABS, 60, 60)).toBe(10);
    expect(carryForwardAt(LABS, 60, 179)).toBe(10);
    expect(carryForwardAt(LABS, 60, 180)).toBe(12);
    expect(carryForwardSeries([0, 60, 180], LABS, 60)).toEqual([null, 10, 12]);
  });

  it("puts each lab on the last series time at or before it, and drops labs outside the series", () => {
    expect(labMarkers([0, 60, 120, 180], LABS)).toEqual([10, null, 12, null]);
    expect(labMarkers([0, 60], LABS)).toEqual([10, null]);
  });

  it("shades only out of range and extrapolation, and drift", () => {
    expect(unreliableMask({ validity: ["ok", "missing_input", "out_of_range", "extrapolation"] })).toEqual([1, 1, 0, 0]);
    expect(driftMask({ drift: [false, true] })).toEqual([1, 0]);
  });

  it("scores the estimate and the baseline against the labs on common points", () => {
    const series = { t_s: [0, 60, 120, 180, 240], estimate: [null, 11, 12, 13, 14], corrected: [null, null, 12, 13, 15] };
    const score = scoreAgainstLabs(series, LABS, 60, 0);
    // Labs at 120 and 240 have a baseline (10 resp. 12) and an estimate; the lab at 0 has no baseline.
    expect(score.n).toBe(2);
    expect(score.estimate).toBeCloseTo(0);
    expect(score.baseline).toBeCloseTo(2);
    expect(score.corrected).toBeCloseTo(Math.sqrt(0.5));
    expect(scoreAgainstLabs(series, LABS, 60, 200).n).toBe(1);
  });

  it("returns nulls when no lab point can be scored", () => {
    const score = scoreAgainstLabs({ t_s: [0], estimate: [null], corrected: [null] }, LABS, 60, 0);
    expect(score).toEqual({ n: 0, estimate: null, corrected: null, baseline: null });
  });
});

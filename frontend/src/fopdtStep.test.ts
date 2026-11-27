// Check the editor's continuous FOPDT response against analytical step values.
// These tests include negative gains, delayed paths and invalid physical parameters.
import { describe, expect, it } from "vitest";
import { fopdtStep } from "./fopdtStep";

const path = { gain: 2, timeConstantS: 10, deadTimeS: 3 };

describe("fopdtStep", () => {
  it("stays at zero before the step reaches the output", () => {
    expect(fopdtStep(path, 2)).toBe(0);
  });
  it("starts at zero exactly at the dead time", () => {
    expect(fopdtStep(path, 3)).toBe(0);
  });
  it("matches the analytic response one time constant after the dead time", () => {
    expect(fopdtStep(path, 13)).toBeCloseTo(2 * (1 - Math.exp(-1)), 14);
  });
  it("preserves a negative gain", () => {
    expect(fopdtStep({ ...path, gain: -2 }, 23)).toBeCloseTo(-2 * (1 - Math.exp(-2)), 14);
  });
  it("returns exact zero before the dead time for a negative gain", () => {
    expect(fopdtStep({ ...path, gain: -2 }, 2)).toBe(0);
  });
  it("approaches the steady state gain", () => {
    expect(fopdtStep(path, 1000)).toBeCloseTo(2, 14);
  });
  it("rejects a nonpositive time constant", () => {
    expect(() => fopdtStep({ ...path, timeConstantS: 0 }, 10)).toThrow(RangeError);
  });
  it("rejects negative dead time", () => {
    expect(() => fopdtStep({ ...path, deadTimeS: -1 }, 10)).toThrow(RangeError);
  });
  it("rejects a nonfinite gain", () => {
    expect(() => fopdtStep({ ...path, gain: Infinity }, 10)).toThrow(RangeError);
  });
  it("rejects a nonfinite plot time", () => {
    expect(() => fopdtStep(path, NaN)).toThrow(RangeError);
  });
});

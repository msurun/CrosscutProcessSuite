// src/windowToRange.test.ts
import { describe, expect, it } from "vitest";
import { windowToRange } from "./trendData";

describe("windowToRange", () => {
  it("offsets the window by the first timestamp on the axis", () => {
    const axis = [1000, 1060, 1120];

    const range = windowToRange(axis, [60, 120]);

    expect(range).toEqual([1060, 1120]);
  });

  it("uses the first timestamp as the minimum for a window starting at zero", () => {
    const axis = [1000, 1060, 1120];

    const range = windowToRange(axis, [0, 60]);

    expect(range).toEqual([1000, 1060]);
  });

  it("returns null when the window is undefined", () => {
    const axis = [1000, 1060, 1120];

    expect(windowToRange(axis, undefined)).toBeNull();
  });

  it("returns null for an empty axis", () => {
    expect(windowToRange([], [60, 120])).toBeNull();
  });

  it("returns null when the first axis entry is null", () => {
    const axis = [null, 1060, 1120];

    expect(windowToRange(axis, [60, 120])).toBeNull();
  });

  it("ignores later axis values when mapping the window", () => {
    const firstAxis = [1000, 1060, 1120];
    const secondAxis = [1000, 5000, 9999];

    const firstRange = windowToRange(firstAxis, [60, 120]);
    const secondRange = windowToRange(secondAxis, [60, 120]);

    expect(firstRange).toEqual(secondRange);
  });
});

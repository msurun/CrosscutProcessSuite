// src/components/TrendPane.test.tsx
import { describe, expect, it } from "vitest";

import { visibleRange } from "../visibleRange";

describe("visibleRange", () => {
  it("returns the plot's own scale when both bounds are set", () => {
    expect(visibleRange(5, 15, [10, 20, 30])).toEqual([5, 15]);
  });

  it("falls back to the first and last time when the scale is not set", () => {
    expect(visibleRange(undefined, undefined, [10, 20, 30])).toEqual([10, 30]);
  });

  it("returns null when there is no data and no scale", () => {
    expect(visibleRange(undefined, undefined, [])).toBeNull();
  });

  it("returns null when a scale bound is not a finite number", () => {
    expect(visibleRange(NaN, 15, [10, 30])).toBeNull();
    expect(visibleRange(5, Infinity, [10, 30])).toBeNull();
  });

  it("returns null when a time stamp used as fallback is not a finite number", () => {
    expect(visibleRange(undefined, undefined, [NaN, 20])).toBeNull();
    expect(visibleRange(undefined, undefined, [10, null])).toBeNull();
  });
});

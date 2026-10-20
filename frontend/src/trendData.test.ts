// src/trendData.test.ts
import { describe, expect, it } from "vitest";
import {
  alignModeToAxis,
  NS_PER_SECOND,
  anyDownsampled,
  nearestIndex,
  rangeToNs,
  toEnvelope,
  toUplotData,
} from "./trendData";
import type { Series } from "./api";

/** Build a series with sensible defaults so each test only states what matters. */
function makeSeries(overrides: Partial<Series> = {}): Series {
  return {
    tag: "turbine.rpm",
    downsampled: false,
    t: [0, 1, 2],
    min: [10, 11, 12],
    max: [20, 21, 22],
    mean: [15, 16, 17],
    ...overrides,
  };
}

describe("toUplotData", () => {
  it("returns a single empty column for an empty series list", () => {
    expect(toUplotData([])).toEqual([[]]);
  });

  it("uses seconds since the first sample as the first column", () => {
    const data = toUplotData([makeSeries({ t: [0, 1e9, 2e9] })]);

    expect(data[0]).toEqual([0, 1, 2]);
  });

  it("appends one mean column per series in order", () => {
    const first = makeSeries({ t: [0, 1], mean: [1, 2] });
    const second = makeSeries({ tag: "turbine.temp", t: [0, 1], mean: [7, 8] });

    const data = toUplotData([first, second]);

    expect(data[1]).toEqual([1, 2]);
    expect(data[2]).toEqual([7, 8]);
  });

  it("passes null mean values through untouched", () => {
    const series = makeSeries({ t: [0, 1, 2], mean: [null, 16, null] });

    const data = toUplotData([series]);

    expect(data[1]).toEqual([null, 16, null]);
  });

  it("throws a RangeError when series time lengths differ", () => {
    const short = makeSeries({ t: [0, 1] });
    const long = makeSeries({ t: [0, 1, 2] });

    expect(() => toUplotData([short, long])).toThrow(RangeError);
  });
});

describe("toEnvelope", () => {
  it("returns copies of the min and max arrays", () => {
    const series = makeSeries({ min: [1, 2], max: [3, 4] });

    const envelope = toEnvelope(series);

    expect(envelope.lower).toEqual([1, 2]);
    expect(envelope.upper).toEqual([3, 4]);
  });

  it("does not alias the source arrays", () => {
    const series = makeSeries({ min: [1, 2], max: [3, 4] });

    const envelope = toEnvelope(series);
    envelope.lower[0] = 99;

    expect(series.min[0]).toBe(1);
  });
});

describe("anyDownsampled", () => {
  it("is false when every series reports full resolution", () => {
    const series = [makeSeries(), makeSeries({ tag: "other" })];

    expect(anyDownsampled(series)).toBe(false);
  });

  it("is true when at least one series was downsampled", () => {
    const series = [makeSeries(), makeSeries({ tag: "other", downsampled: true })];

    expect(anyDownsampled(series)).toBe(true);
  });

  it("is false for an empty series list", () => {
    expect(anyDownsampled([])).toBe(false);
  });
});

describe("rangeToNs", () => {
  it("returns an empty range for the all preset", () => {
    expect(rangeToNs(5000, "all")).toEqual({});
  });

  it("spans one hour before the end for the 1h preset", () => {
    const range = rangeToNs(7200, "1h");

    expect(range.endNs).toBe(7200 * NS_PER_SECOND);
    expect(range.startNs).toBe(7200 * NS_PER_SECOND - 3600 * NS_PER_SECOND);
  });

  it("spans eight hours before the end for the 8h preset", () => {
    const range = rangeToNs(100000, "8h");

    expect(range.startNs).toBe(100000 * NS_PER_SECOND - 8 * 3600 * NS_PER_SECOND);
  });

  it("spans twenty four hours before the end for the 24h preset", () => {
    const range = rangeToNs(100000, "24h");

    expect(range.startNs).toBe(100000 * NS_PER_SECOND - 24 * 3600 * NS_PER_SECOND);
  });
});

describe("nearestIndex", () => {
  it("returns minus one for an empty time array", () => {
    expect(nearestIndex([], 42)).toBe(-1);
  });

  it("returns the first index when the target sits before the start", () => {
    expect(nearestIndex([10, 20, 30], 5)).toBe(0);
  });

  it("returns the last index when the target sits after the end", () => {
    expect(nearestIndex([10, 20, 30], 999)).toBe(2);
  });

  it("returns the index of an exact match in the middle", () => {
    expect(nearestIndex([10, 20, 30], 20)).toBe(1);
  });

  it("returns the closer neighbour when the target is not a sample", () => {
    expect(nearestIndex([10, 20, 30], 26)).toBe(2);
  });

  it("returns the lower neighbour when the target is equidistant from two samples", () => {
    expect(nearestIndex([10, 20, 30], 25)).toBe(1);
  });

  it("handles a single sample array", () => {
    expect(nearestIndex([10], 1000)).toBe(0);
  });
});

describe("alignModeToAxis", () => {
  it("resamples a coarser MODE series onto the PV axis by nearest sample", () => {
    const mode = { tag: "M", downsampled: false, t: [0, 10e9], min: [], max: [], mean: [1, 0] };
    expect(alignModeToAxis([0, 2, 8, 10], mode)).toEqual([1, 1, 0, 0]);
  });

  it("gives all null for an empty MODE series", () => {
    const mode = { tag: "M", downsampled: false, t: [], min: [], max: [], mean: [] };
    expect(alignModeToAxis([0, 1], mode)).toEqual([null, null]);
  });
});

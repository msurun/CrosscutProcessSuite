// Tests for trendChartData: timestamp merging, pane shaping and the parallel loader.
// Timestamps are nanoseconds since epoch; uPlot x values are seconds.

import { describe, expect, it, vi } from "vitest";
import type { DatasetSummary, Series } from "./api";
import { dataEndNs, loadChartData, mergeColumns, shapePanes } from "./trendChartData";
import type { TrendChart } from "./trendChartsApi";

const S = 1e9;
const ser = (tag: string, t: number[], mean: (number | null)[], downsampled = false): Series => ({
  tag, downsampled, t: t.map((x) => x * S), min: mean, max: mean, mean,
});

const chart: TrendChart = {
  schema_version: 1, id: "c", name: "c", owner: "o", shared: false, created_utc: "", updated_utc: "",
  series: [
    { source: "d1", tag: "A", axis: "y1", label: "Alpha", colour: "#112233" },
    { source: "d2", tag: "B", axis: "y2" },
    { source: "d1", tag: "C", axis: "y1" },
  ],
  axes: [
    { id: "y1", side: "left", unit: "%" },
    { id: "y2", side: "right", pane: 1, min: 0, max: 5 },
  ],
  window: { kind: "relative", last_s: 100 },
};

const datasets = (ends: Record<string, string>): DatasetSummary[] =>
  Object.entries(ends).map(([id, end]) => ({
    id, source: {}, time_range: { start_utc: "2026-01-01T00:00:00Z", end_utc: end }, n_tags: 1, n_samples: 1,
  }));

describe("mergeColumns", () => {
  it("unions timestamps and fills gaps with null", () => {
    const out = mergeColumns([ser("a", [1, 3], [10, 30]), ser("b", [2, 3], [20, 31])]);
    expect(out).toEqual([[1, 2, 3], [10, null, 30], [null, 20, 31]]);
  });
  it("returns only an empty x column for no series", () => {
    expect(mergeColumns([])).toEqual([[]]);
  });
});

describe("dataEndNs", () => {
  it("takes the latest end among used datasets only", () => {
    const d = datasets({ d1: "2026-01-02T00:00:00Z", d2: "2026-01-03T00:00:00Z", x: "2027-01-01T00:00:00Z" });
    expect(dataEndNs(chart, d)).toBe(Date.parse("2026-01-03T00:00:00Z") * 1e6);
  });
  it("is undefined when no dataset matches", () => {
    expect(dataEndNs(chart, datasets({ x: "2026-01-02T00:00:00Z" }))).toBeUndefined();
  });
});

describe("shapePanes", () => {
  const map = new Map<string, Series>([
    ["d1\u0000A", ser("A", [1], [1])],
    ["d1\u0000C", ser("C", [1], [3])],
  ]);
  it("groups by pane, styles series and nulls missing ones", () => {
    const panes = shapePanes(chart, map);
    expect(panes.map((p) => p.pane)).toEqual([0, 1]);
    expect(panes[0].labels).toEqual(["Alpha", "C"]);
    expect(panes[0].colors).toEqual(["#112233", "--series-3"]);
    expect(panes[0].seriesAxis).toEqual(["y1", "y1"]);
    expect(panes[0].axes.map((a) => a.id)).toEqual(["y1"]);
    expect(panes[1].axes[0]).toMatchObject({ id: "y2", side: "right", min: 0, max: 5 });
    expect(panes[1].data).toEqual([[], []]);
  });
});

describe("loadChartData", () => {
  it("fetches once per source and reports downsampling", async () => {
    const fetcher = vi.fn(async (src: string, tags: string[]) =>
      tags.map((t) => ser(t, [1, 2], [1, 2], src === "d2")));
    const d = datasets({ d1: "2026-01-01T00:10:00Z" });
    const out = await loadChartData(chart, d, 0, fetcher);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls[0][1]).toEqual(["A", "C"]);
    expect(out.downsampled).toBe(true);
    expect(out.endNs).toBe(Date.parse("2026-01-01T00:10:00Z") * 1e6);
    expect(out.startNs).toBe(out.endNs - 100 * S);
    expect(out.panes[0].data[0]).toEqual([1, 2]);
  });
});

// Turns a saved TrendChart into per-pane uPlot data: fetches series per source, merges the
// timestamps of each pane into one x column and attaches axes, labels and colours.
// Pure helpers plus one async loader; the fetcher is injected so tests need no network.

import type { DatasetSummary, Series } from "./api";
import type { PaneAxis } from "./components/TrendPane";
import type { TrendChart, TrendSeries } from "./trendChartsApi";
import { NS_PER_SECOND } from "./trendData";
import { resolveWindow } from "./trendWindow";

/** One pane of a chart: uPlot data (x in seconds, then one column per series) plus styling. */
export interface ChartPane {
  pane: number;
  axes: PaneAxis[];
  seriesAxis: string[];
  labels: string[];
  colors: string[];
  data: (number | null)[][];
}

/** A fully loaded chart: its panes, whether any series was downsampled and the window in ns. */
export interface ChartData {
  panes: ChartPane[];
  downsampled: boolean;
  startNs: number;
  endNs: number;
}

/** Fetches the named tags of one source (dataset) for a time range given in ns since epoch. */
export type SeriesFetcher = (
  source: string,
  tags: string[],
  range: { startNs: number; endNs: number },
) => Promise<Series[]>;

/** A chart series with its chart-wide 0-based index (used for the default colour). */
interface Member {
  s: TrendSeries;
  n: number;
}

/** Map key of one series: source and tag joined by a NUL, which neither can contain. */
function seriesKey(source: string, tag: string): string {
  return `${source}\u0000${tag}`;
}

/** Latest end_utc (ns since epoch) of the datasets the chart reads; undefined if none is known. */
export function dataEndNs(chart: TrendChart, datasets: DatasetSummary[]): number | undefined {
  const sources = new Set(chart.series.map((s) => s.source));
  const ends = datasets
    .filter((d) => sources.has(d.id))
    .map((d) => Date.parse(d.time_range.end_utc) * 1e6)
    .filter((n) => Number.isFinite(n));
  return ends.length > 0 ? Math.max(...ends) : undefined;
}

/** Union of all timestamps (sorted, in seconds) with one mean column per series, null where absent. */
export function mergeColumns(series: Series[]): (number | null)[][] {
  const times = [...new Set(series.flatMap((s) => s.t))].sort((a, b) => a - b);
  const columns = series.map((s) => {
    const byTime = new Map(s.t.map((t, i) => [t, s.mean[i] ?? null] as const));
    return times.map((t) => byTime.get(t) ?? null);
  });
  return [times.map((t) => t / NS_PER_SECOND), ...columns];
}

/** An empty series (no samples) standing in for one the fetcher did not return. */
function emptySeries(tag: string): Series {
  return { tag, downsampled: false, t: [], min: [], max: [], mean: [] };
}

/** Build one pane from the chart series that belong to it. */
function buildPane(
  chart: TrendChart,
  pane: number,
  members: Member[],
  seriesByKey: Map<string, Series>,
): ChartPane {
  const used = new Set(members.map((m) => m.s.axis));
  const axes = chart.axes
    .filter((a) => used.has(a.id))
    .map(({ id, side, unit, min, max }) => ({ id, side, unit, min, max }));
  const data = mergeColumns(
    members.map((m) => seriesByKey.get(seriesKey(m.s.source, m.s.tag)) ?? emptySeries(m.s.tag)),
  );
  return {
    pane,
    axes,
    seriesAxis: members.map((m) => m.s.axis),
    labels: members.map((m) => m.s.label || m.s.tag),
    colors: members.map((m) => m.s.colour || `--series-${m.n + 1}`),
    data,
  };
}

/** Group the chart series by the pane of their axis (ascending) and build each pane. */
export function shapePanes(chart: TrendChart, seriesByKey: Map<string, Series>): ChartPane[] {
  const paneOf = new Map(chart.axes.map((a) => [a.id, a.pane ?? 0]));
  const groups = new Map<number, Member[]>();
  chart.series.forEach((s, n) => {
    const pane = paneOf.get(s.axis) ?? 0;
    groups.set(pane, [...(groups.get(pane) ?? []), { s, n }]);
  });
  return [...groups.keys()]
    .sort((a, b) => a - b)
    .map((pane) => buildPane(chart, pane, groups.get(pane) ?? [], seriesByKey));
}

/** Tags of the chart grouped by source (deduplicated, in first-seen order). */
function tagsBySource(chart: TrendChart): Map<string, string[]> {
  const bySource = new Map<string, string[]>();
  for (const s of chart.series) {
    const tags = bySource.get(s.source) ?? [];
    if (!tags.includes(s.tag)) tags.push(s.tag);
    bySource.set(s.source, tags);
  }
  return bySource;
}

/** Resolve the window once, fetch every source in parallel and shape the panes. */
export async function loadChartData(
  chart: TrendChart,
  datasets: DatasetSummary[],
  nowMs: number,
  fetcher: SeriesFetcher,
): Promise<ChartData> {
  const range = resolveWindow(chart.window, nowMs, dataEndNs(chart, datasets));
  const entries = [...tagsBySource(chart)];
  const results = await Promise.all(entries.map(([src, tags]) => fetcher(src, tags, range)));
  const seriesByKey = new Map<string, Series>();
  entries.forEach(([src], i) => results[i].forEach((s) => seriesByKey.set(seriesKey(src, s.tag), s)));
  const downsampled = results.some((list) => list.some((s) => s.downsampled));
  return { panes: shapePanes(chart, seriesByKey), downsampled, ...range };
}

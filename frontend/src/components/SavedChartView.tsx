// src/components/SavedChartView.tsx
// Draws one saved trend chart (#205, #206): loads its series for the chart's time window, one
// TrendPane per pane with that pane's y-axes, and reloads on a timer while the window follows live data.
import { useEffect, useState } from "react";

import { fetchSeries, type DatasetSummary } from "../api";
import type { Translate } from "../findings";
import { loadChartData, type ChartData, type SeriesFetcher } from "../trendChartData";
import type { TrendChart } from "../trendChartsApi";
import { isLive } from "../trendWindow";
import { TrendPane } from "./TrendPane";

/** Height in pixels of one chart pane. */
const PANE_HEIGHT_PX = 260;
/** Most points the backend returns per series; enough for a full-width pane. */
const MAX_POINTS = 1500;
/** Milliseconds per second, for the live refresh timer. */
const MS_PER_S = 1000;

/** Reads a dataset's series through the existing dataset API (sources are dataset ids for now). */
const fetchFromDataset: SeriesFetcher = async (source, tags, range) =>
  (await fetchSeries(source, tags, { startNs: range.startNs, endNs: range.endNs, maxPoints: MAX_POINTS })).series;

/** Current time in ms, ticking every `refresh_s` while the chart window is live. */
function useNow(chart: TrendChart): number {
  const [now, setNow] = useState(() => Date.now());
  const live = isLive(chart.window);
  const periodS = chart.window.kind === "relative" ? (chart.window.refresh_s ?? 10) : 0;
  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => setNow(Date.now()), periodS * MS_PER_S);
    return () => window.clearInterval(timer);
  }, [live, periodS]);
  return now;
}

type Load = { status: "loading" } | { status: "error"; reason: string } | { status: "ready"; data: ChartData };

/** Loads the chart data again whenever the chart, its window or the clock changes; stale answers are dropped. */
function useChartData(chart: TrendChart, datasets: DatasetSummary[], nowMs: number): Load {
  const [load, setLoad] = useState<Load>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    loadChartData(chart, datasets, nowMs, fetchFromDataset)
      .then((data) => !cancelled && setLoad({ status: "ready", data }))
      .catch((error: unknown) => !cancelled && setLoad({ status: "error", reason: error instanceof Error ? error.message : String(error) }));
    return () => {
      cancelled = true;
    };
  }, [chart, datasets, nowMs]);
  return load;
}

interface SavedChartViewProps {
  chart: TrendChart;
  datasets: DatasetSummary[];
  t: Translate;
}

/** The panes of a saved chart, with loading, error and downsampled states. */
export function SavedChartView({ chart, datasets, t }: SavedChartViewProps) {
  const nowMs = useNow(chart);
  const load = useChartData(chart, datasets, nowMs);
  if (load.status === "loading") return <p className="status">{t("trends.loading")}</p>;
  if (load.status === "error") return <p className="status status-error">{t("trends.error", { reason: load.reason })}</p>;
  return (
    <>
      {load.data.downsampled && <span className="badge">{t("trends.downsampled")}</span>}
      {load.data.panes.map((pane) => (
        <TrendPane
          key={`${chart.id}-${pane.pane}-${pane.axes.map((a) => a.id).join(",")}`}
          timeLabel={t("trends.time")}
          data={pane.data}
          labels={pane.labels}
          colors={pane.colors}
          yAxes={pane.axes}
          seriesAxis={pane.seriesAxis}
          height={PANE_HEIGHT_PX}
          syncKey={`chart-${chart.id}`}
          t={t}
        />
      ))}
    </>
  );
}

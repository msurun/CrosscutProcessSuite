// src/components/TrendsPage.tsx
// The Trends view: loads the series of the selected tags, shows at most 3 unit panes at first
// (the rest behind a button) and a shared cursor readout with the value of every plotted series.
import { useCallback, useEffect, useMemo, useState } from "react";

import { fetchSeries, type DatasetSummary, type Series, type TagInfo } from "../api";
import type { Translate } from "../findings";
import { formatFixed } from "../format";
import { anyDownsampled, buildUnitGroups, nearestIndex, NS_PER_SECOND, toUplotData, type UnitGroup } from "../trendData";
import { SavedChartsWorkspace } from "./SavedChartsWorkspace";
import { TrendPane } from "./TrendPane";

/** Maximum number of points the backend may return per series. */
const MAX_POINTS = 1500;
/** Height in pixels of every trend pane. */
const TREND_PANE_HEIGHT_PX = 260;
/** Panes shown before the user asks for more. */
export const MAX_AUTO_PANES = 3;
/** Decimals of the cursor readout values. */
const READOUT_DECIMALS = 2;

/** Lifecycle of the series request for the current dataset + tag selection. */
type Status = "idle" | "loading" | "error";

interface TrendsPageProps {
  datasetId: string;
  /** The open dataset; its end time anchors relative windows of saved charts. */
  dataset?: DatasetSummary;
  tags: TagInfo[];
  selectedTags: readonly string[];
  t: Translate;
}

/** Loads the series of the selected tags, ignoring stale responses. */
function useSeries(datasetId: string, selectedTags: readonly string[]) {
  const [series, setSeries] = useState<Series[]>([]);
  const [status, setStatus] = useState<Status>("idle");
  const [errorReason, setErrorReason] = useState("");

  useEffect(() => {
    if (datasetId === "" || selectedTags.length === 0) {
      setSeries([]);
      setStatus("idle");
      setErrorReason("");
      return;
    }
    let isCancelled = false;
    setStatus("loading");
    fetchSeries(datasetId, selectedTags, { maxPoints: MAX_POINTS })
      .then((response) => {
        if (isCancelled) return;
        setSeries(response.series);
        setStatus("idle");
      })
      .catch((error: unknown) => {
        if (isCancelled) return;
        setSeries([]);
        setStatus("error");
        setErrorReason(error instanceof Error ? error.message : String(error));
      });
    return () => {
      isCancelled = true;
    };
  }, [datasetId, selectedTags]);

  return { series, status, errorReason };
}

/** Value of series `index` of `group` at `seconds`, with its unit, or "--" without a cursor or sample. */
function readoutValue(group: UnitGroup, index: number, seconds: number | null): string {
  const one = group.series[index];
  const at = seconds === null ? -1 : nearestIndex(one.t.map((n) => n / NS_PER_SECOND), seconds);
  const value = at < 0 ? null : one.mean[at];
  return value === null ? "--" : `${formatFixed(value, READOUT_DECIMALS)} ${group.unit}`.trim();
}

/** The row of values of all plotted series at the cursor time. */
function CursorReadout(props: { groups: UnitGroup[]; seconds: number | null; t: Translate }) {
  return (
    <div role="group" aria-label={props.t("trends.readout")}>
      <p className="trend-readout-title">{props.t("trends.readout")}</p>
      {/* The hint keeps its space while hidden, so the charts below do not jump when the cursor enters a plot. */}
      <p className="status" style={{ visibility: props.seconds === null ? "visible" : "hidden" }}>{props.t("trends.readoutNone")}</p>
      <ul className="trend-readout">
        {props.groups.flatMap((group) =>
          group.labels.map((label, index) => (
            <li key={label}>
              {label}: <strong>{readoutValue(group, index, props.seconds)}</strong>
            </li>
          )),
        )}
      </ul>
    </div>
  );
}

/** Trend panes (capped) with the "show more" button. */
function PaneList(props: { groups: UnitGroup[]; t: Translate; onCursor: (seconds: number | null) => void }) {
  const [showAll, setShowAll] = useState(false);
  const shown = showAll ? props.groups : props.groups.slice(0, MAX_AUTO_PANES);
  const hidden = props.groups.length - shown.length;
  return (
    <>
      {shown.map((group) => (
        <TrendPane
          key={group.unit}
          timeLabel={props.t("trends.time")}
          data={toUplotData(group.series)}
          labels={group.labels}
          colors={group.colors}
          unit={group.unit}
          height={TREND_PANE_HEIGHT_PX}
          syncKey="trends"
          t={props.t}
          onCursor={props.onCursor}
        />
      ))}
      {hidden > 0 && (
        <button type="button" className="filter-chip" onClick={() => setShowAll(true)}>
          {props.t("trends.showMorePanes", { count: hidden })}
        </button>
      )}
    </>
  );
}

/** The quick view: the tags picked in the sidebar, one pane per unit. */
function QuickTrends({ datasetId, tags, selectedTags, t }: TrendsPageProps) {
  const { series, status, errorReason } = useSeries(datasetId, selectedTags);
  const [cursor, setCursor] = useState<number | null>(null);
  const groups = useMemo(() => buildUnitGroups(series, tags), [series, tags]);
  const onCursor = useCallback((seconds: number | null) => setCursor(seconds), []);

  if (status === "loading") return <p className="status">{t("trends.loading")}</p>;
  if (status === "error") return <p className="status status-error">{t("trends.error", { reason: errorReason })}</p>;
  if (selectedTags.length === 0) return <p className="status">{t("trends.noData")}</p>;
  return (
    <>
      {anyDownsampled(series) && <span className="badge">{t("trends.downsampled")}</span>}
      <CursorReadout groups={groups} seconds={cursor} t={t} />
      <PaneList key={datasetId} groups={groups} t={t} onCursor={onCursor} />
    </>
  );
}

/** Which side of the Trends view is shown. */
type TrendsMode = "quick" | "saved";

/** The Trends view: the quick view of the sidebar tags, or the saved charts (#204-#207). */
export function TrendsPage(props: TrendsPageProps) {
  const [mode, setMode] = useState<TrendsMode>("quick");
  const { t } = props;
  return (
    <>
      <div className="trend-toolbar" role="group" aria-label={t("trendCharts.modes")}>
        {(["quick", "saved"] as const).map((m) => (
          <button key={m} type="button" aria-pressed={mode === m} onClick={() => setMode(m)}>
            {t(`trendCharts.${m}`)}
          </button>
        ))}
      </div>
      {mode === "quick" ? (
        <QuickTrends {...props} />
      ) : (
        <SavedChartsWorkspace datasetId={props.datasetId} dataset={props.dataset} tags={props.tags} t={t} />
      )}
    </>
  );
}

// src/components/LoopDetail.tsx
//
// Detail view for a single control loop: why the loop is flagged, the concrete
// numbers behind that verdict, and two trend panes (PV/SP and controller output).
// Data is loaded once per (datasetId, loop) pair from the backend.

import { useEffect, useState } from "react";
import type { LoopSummary, Series } from "../api";
import { fetchSeries } from "../api";
import { toUplotData, windowToRange } from "../trendData";
import { TrendPane } from "./TrendPane";
import { StatusChip } from "./StatusChip";
import { findingText, nextStepTexts, type Translate } from "../findings";

/** Maximum number of points requested per trend series. */
const TREND_MAX_POINTS = 1500;

/** Seconds in a minute, used to render an oscillation period in minutes. */
const SECONDS_PER_MINUTE = 60;

/** Placeholder shown when a nullable key number has no value. */
const NOT_AVAILABLE = "–";

/** Series that are drawn in the first pane, in drawing order. */
const PV_SP_COLORS = ["--series-1", "--series-2"] as const;

/** Colour of the controller output series in the second pane. */
const OUT_COLOR = "--series-3";

/** Unit of the controller output series, which is always a percentage. */
const OUT_UNIT = "%";

type SeriesState =
  | { status: "loading" }
  | { status: "error"; reason: string }
  | { status: "ready"; series: Series[] };

/**
 * Loads the PV, SP and OUT series of one loop.
 *
 * Returns the load state; the caller renders loading, error or trend panes.
 * The request is cancelled when the dataset or the loop changes so a late
 * response never overwrites the series of another loop.
 */
function useLoopSeries(datasetId: string, loop: LoopSummary): SeriesState {
  const [state, setState] = useState<SeriesState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });

    fetchSeries(datasetId, [loop.pv, loop.sp, loop.out], { maxPoints: TREND_MAX_POINTS })
      .then((result) => {
        if (!cancelled) setState({ status: "ready", series: result.series });
      })
      .catch((error: unknown) => {
        if (!cancelled) setState({ status: "error", reason: String(error) });
      });

    return () => {
      cancelled = true;
    };
  }, [datasetId, loop.pv, loop.sp, loop.out]);

  return state;
}

/** Outcome of picking series by tag: the matches in tag order, or the reason one is missing. */
type PickResult = { ok: true; series: Series[] } | { ok: false; reason: string };

/**
 * Picks the series matching the given tags, keeping the tag order.
 *
 * Returns a failure instead of throwing, so a backend response without one tag
 * shows an error message in the trends rather than crashing the whole view.
 */
function pickSeries(series: readonly Series[], tags: readonly string[]): PickResult {
  const picked: Series[] = [];
  for (const tag of tags) {
    const match = series.find((candidate) => candidate.tag === tag);
    if (match === undefined) {
      return { ok: false, reason: `Series "${tag}" is missing from the backend response.` };
    }
    picked.push(match);
  }
  return { ok: true, series: picked };
}

/** Formats a nullable number with the given number of decimals, or a dash. */
function formatNumber(value: number | null, decimals: number): string {
  return value === null ? NOT_AVAILABLE : value.toFixed(decimals);
}

/** One term/definition pair of the key-numbers list. */
function KeyNumber({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

/** The compact list of numbers behind the loop verdict. */
function KeyNumbers({ loop, t }: { loop: LoopSummary; t: Translate }) {
  const oscillation =
    loop.oscillation_period_s === null
      ? NOT_AVAILABLE
      : t("loops.minutes", { value: (loop.oscillation_period_s / SECONDS_PER_MINUTE).toFixed(1) });

  return (
    <dl className="key-numbers">
      <KeyNumber label={t("loops.inUse")} value={`${loop.service_percent} %`} />
      <KeyNumber label={t("loops.saturated")} value={`${loop.saturation_percent} %`} />
      <KeyNumber label={t("loops.harris")} value={formatNumber(loop.harris_index, 2)} />
      <KeyNumber label={t("loops.oscillation")} value={oscillation} />
    </dl>
  );
}

/** The findings that explain why the loop is flagged; one with a data window can zoom the trends. */
function Findings({
  loop,
  t,
  onShow,
}: {
  loop: LoopSummary;
  t: Translate;
  onShow: (window: [number, number] | undefined) => void;
}) {
  if (loop.findings.length === 0) {
    return <p>{t("loops.noFindings")}</p>;
  }

  return (
    <>
      {loop.findings.map((finding, index) => (
        // Findings carry no id from the backend, so the index identifies them.
        <p key={index}>
          {findingText(t, finding)}
          {finding.window_s !== undefined && (
            <>
              {" "}
              <button type="button" className="link-button" onClick={() => onShow(finding.window_s)}>
                {finding.window_kind === "example" ? t("loops.showExampleInTrend") : t("loops.showInTrend")}
              </button>
            </>
          )}
        </p>
      ))}
    </>
  );
}

/** The numbered list of actions suggested for the loop. */
function NextSteps({ loop, t }: { loop: LoopSummary; t: Translate }) {
  return (
    <ul>
      {nextStepTexts(t, loop).map((text, index) => (
        // Action texts are plain strings; the index is the only stable key.
        <li key={index}>{text}</li>
      ))}
    </ul>
  );
}

/** The two trend panes, or the loading/error message replacing them. */
function Trends({
  state,
  loop,
  t,
  window,
}: {
  state: SeriesState;
  loop: LoopSummary;
  t: Translate;
  window: [number, number] | undefined;
}) {
  if (state.status === "loading") {
    return <p className="status">{t("trends.loading")}</p>;
  }
  if (state.status === "error") {
    return <p className="status status-error">{t("trends.error", { reason: state.reason })}</p>;
  }

  const picked = pickSeries(state.series, [loop.pv, loop.sp, loop.out]);
  if (!picked.ok) {
    return <p className="status status-error">{t("trends.error", { reason: picked.reason })}</p>;
  }

  const pvSp = picked.series.slice(0, 2);
  const out = picked.series.slice(2);
  const pvSpData = toUplotData(pvSp);
  const outData = toUplotData(out);
  // Both panes share the time axis, so one window gives the same range for both.
  const range = windowToRange(pvSpData[0], window);

  return (
    <>
      <TrendPane
        data={pvSpData}
        labels={[loop.pv, loop.sp]}
        colors={[...PV_SP_COLORS]}
        unit={loop.unit}
        xRange={range}
      />
      <TrendPane
        data={outData}
        labels={[loop.out]}
        colors={[OUT_COLOR]}
        unit={OUT_UNIT}
        xRange={range}
      />
    </>
  );
}

/**
 * Full detail view of one control loop.
 *
 * Renders the findings, the key numbers and the PV/SP and OUT trends. The trends
 * load from the backend whenever the dataset or the loop changes.
 */
export function LoopDetail({
  datasetId,
  loop,
  t,
  onBack,
  onOpenTuning,
  onOpenBenefit,
}: {
  datasetId: string;
  loop: LoopSummary;
  t: Translate;
  onBack: () => void;
  onOpenTuning: () => void;
  onOpenBenefit: () => void;
}) {
  const seriesState = useLoopSeries(datasetId, loop);
  const [shownWindow, setShownWindow] = useState<[number, number] | undefined>(undefined);

  return (
    <>
      <button type="button" className="link-button" onClick={onBack}>
        ← {t("loops.back")}
      </button>

      <h2 className="loop-header">
        {loop.name}
        <StatusChip level={loop.status} label={t(`status.${loop.status}`)} />
        {loop.health_percent !== null && t("health.label", { percent: loop.health_percent })}
      </h2>

      <p>
        <button type="button" className="filter-chip" onClick={onOpenTuning}>
          {t("tuning.title")}
        </button>{" "}
        <button type="button" className="filter-chip" onClick={onOpenBenefit}>
          {t("benefit.title")}
        </button>
      </p>

      <div className="loop-detail-grid">
        <div>
          <section>
            <h3>{t("loops.why")}</h3>
            <Findings loop={loop} t={t} onShow={setShownWindow} />
          </section>
          <section>
            <h3>{t("loops.nextSteps")}</h3>
            <NextSteps loop={loop} t={t} />
          </section>
        </div>
        <section>
          <h3>{t("loops.keyNumbers")}</h3>
          <KeyNumbers loop={loop} t={t} />
        </section>
      </div>

      <section>
        {shownWindow !== undefined && (
          <button type="button" className="link-button" onClick={() => setShownWindow(undefined)}>
            {t("loops.showAll")}
          </button>
        )}
        <Trends state={seriesState} loop={loop} t={t} window={shownWindow} />
      </section>
    </>
  );
}

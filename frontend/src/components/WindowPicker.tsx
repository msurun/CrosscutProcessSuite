// src/components/WindowPicker.tsx
//
// Free window chooser for the tuning page: the user picks any start and end on
// the recorded loop, by zooming the trends or by typing minutes. This complements
// the suggested-window chips, which only offer the windows the analysis found.

import { useEffect, useMemo, useState } from "react";
import type { LoopSummary, Series } from "../api";
import { fetchSeries } from "../api";
import { toUplotData, windowToRange } from "../trendData";
import { TrendPane } from "./TrendPane";
import { formatFixed } from "../format";
import type { Translate } from "../findings";

/** Maximum number of points requested per trend series. */
const TREND_MAX_POINTS = 1500;

/** Chart height of both panes, in pixels. */
const PANE_HEIGHT_PX = 160;

/** Sync key shared by the two panes so their crosshairs follow each other. */
const SYNC_KEY = "tuning-window";

/** Seconds in a minute: the text inputs are in minutes, the API is in seconds. */
const SECONDS_PER_MINUTE = 60;

/** Tolerance for comparing window bounds to the record length, in seconds (float rounding). */
const BOUND_TOLERANCE_S = 1e-6;

/** Colours of the PV series, matching the detail view's first pane. */
const PV_COLOR = "--series-1";

/** Colour of the controller output series, matching the detail view's second pane. */
const OUT_COLOR = "--series-3";

/** Unit of the controller output series, which is always a percentage. */
const OUT_UNIT = "%";

/** A window on the plot's time axis, in seconds since the Unix epoch. */
type VisibleRange = readonly [number, number];

/** A window relative to the first sample of the record, in seconds. */
interface AnalysisWindow {
  startS: number;
  endS: number;
}

/** A window selected on the plot, translated to seconds since the first sample. */
interface ClosedWindow extends AnalysisWindow {}

type SeriesState =
  | { status: "loading" }
  | { status: "error"; reason: string }
  | { status: "ready"; series: Series[] };

/**
 * Parse a minute value typed by the user.
 *
 * Accepts a decimal comma ("1,5") as well as a point ("1.5"), because a comma
 * is the decimal separator in many locales.
 *
 * @returns The finite, non-negative number of minutes, or null when the text is
 * not such a number (empty text, letters, negative values).
 */
export function parseMinutes(text: string): number | null {
  const normalized = text.trim().replace(",", ".");
  if (normalized === "") {
    return null;
  }
  const value = Number(normalized);
  if (!Number.isFinite(value) || value < 0) {
    return null;
  }
  return value;
}

/**
 * Decide whether a window is usable on a record of the given length.
 *
 * @param startS Start in seconds since the first sample.
 * @param endS End in seconds since the first sample.
 * @param recordS Record length in seconds.
 * @returns True when start >= 0, end > start and end <= recordS (within rounding).
 */
export function isValidWindow(startS: number, endS: number, recordS: number): boolean {
  return startS >= 0 && endS > startS && endS <= recordS + BOUND_TOLERANCE_S;
}

/**
 * Clamp a window to [0, recordS] and keep it non-empty.
 *
 * A zoom can drag the bounds slightly outside the record; the result is always
 * a window that passes {@link isValidWindow}.
 */
function clampWindow(window: ClosedWindow, recordS: number): ClosedWindow {
  const startS = Math.min(Math.max(window.startS, 0), recordS);
  const endS = Math.min(Math.max(window.endS, startS), recordS);
  return { startS, endS };
}

/**
 * Load the PV and OUT series of one loop.
 *
 * Returns the load state; a late response is dropped when the dataset or the
 * loop changes, so it never overwrites the series of another loop.
 */
function useLoopSeries(datasetId: string, loop: LoopSummary): SeriesState {
  const [state, setState] = useState<SeriesState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });

    fetchSeries(datasetId, [loop.pv, loop.out], { maxPoints: TREND_MAX_POINTS })
      .then((result) => {
        if (!cancelled) setState({ status: "ready", series: result.series });
      })
      .catch((error: unknown) => {
        if (!cancelled) setState({ status: "error", reason: String(error) });
      });

    return () => {
      cancelled = true;
    };
  }, [datasetId, loop.pv, loop.out]);

  return state;
}

/** Minutes as the text of an input: at most one decimal, using the locale separator. */
function minutesText(seconds: number): string {
  return formatFixed(seconds / SECONDS_PER_MINUTE, 1);
}

/**
 * The two typed minute fields, their state and the apply handler.
 *
 * The text is resynced whenever the `window` prop changes, so a chip chosen on
 * another part of the page shows up here.
 */
function useMinuteInputs(
  window: { startS: number; endS: number } | null,
  recordS: number,
  onSelectWindow: (w: AnalysisWindow) => void,
): {
  startText: string;
  endText: string;
  setStartText: (text: string) => void;
  setEndText: (text: string) => void;
  parsed: { startS: number; endS: number } | null;
  canApply: boolean;
  isInvalid: boolean;
  apply: () => void;
} {
  const [startText, setStartText] = useState(window === null ? "" : minutesText(window.startS));
  const [endText, setEndText] = useState(window === null ? "" : minutesText(window.endS));

  useEffect(() => {
    setStartText(window === null ? "" : minutesText(window.startS));
    setEndText(window === null ? "" : minutesText(window.endS));
  }, [window?.startS, window?.endS]);

  const startMinutes = parseMinutes(startText);
  const endMinutes = parseMinutes(endText);
  const parsed =
    startMinutes === null || endMinutes === null
      ? null
      : { startS: startMinutes * SECONDS_PER_MINUTE, endS: endMinutes * SECONDS_PER_MINUTE };
  const canApply = parsed !== null && isValidWindow(parsed.startS, parsed.endS, recordS);
  // Both fields parse, but the window does not fit the record: explain why.
  const isInvalid = parsed !== null && !canApply;

  const apply = () => {
    if (parsed !== null && canApply) {
      onSelectWindow(parsed);
    }
  };

  return { startText, endText, setStartText, setEndText, parsed, canApply, isInvalid, apply };
}

/** One labelled minute input. */
function MinuteField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (text: string) => void;
}) {
  return (
    <label className="field-label">
      {label}
      <input
        className="field-input"
        type="text"
        inputMode="decimal"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

/** The two trend panes of the picker, or the loading/error message replacing them. */
function WindowTrends({
  state,
  loop,
  t,
  xRange,
  onZoom,
}: {
  state: SeriesState;
  loop: LoopSummary;
  t: Translate;
  xRange: readonly [number, number] | null;
  onZoom: (minSeconds: number, maxSeconds: number) => void;
}) {
  // The data arrays must keep their identity between renders: TrendPane resets the visible range
  // whenever `data` changes, and onZoom re-renders this component, which would loop forever.
  const columns = useMemo(() => (state.status === "ready" ? toUplotData(state.series) : null), [state]);
  const pvData = useMemo(() => (columns ? [columns[0], columns[1]] : null), [columns]);
  const outData = useMemo(() => (columns ? [columns[0], columns[2]] : null), [columns]);
  if (state.status === "loading") {
    return <p className="status">{t("tuning.window.loadingTrend")}</p>;
  }
  if (state.status === "error") {
    return <p className="status status-error">{t("trends.error", { reason: state.reason })}</p>;
  }
  if (!pvData || !outData) return null;

  return (
    <>
      <TrendPane
        timeLabel={t("trends.time")}
        data={pvData}
        labels={[t("tuning.window.pvLabel")]}
        colors={[PV_COLOR]}
        unit={loop.unit}
        height={PANE_HEIGHT_PX}
        syncKey={SYNC_KEY}
        xRange={xRange}
        onZoom={onZoom}
      />
      <TrendPane
        timeLabel={t("trends.time")}
        data={outData}
        labels={[t("tuning.window.outLabel")]}
        colors={[OUT_COLOR]}
        unit={OUT_UNIT}
        height={PANE_HEIGHT_PX}
        syncKey={SYNC_KEY}
        xRange={xRange}
        onZoom={onZoom}
      />
    </>
  );
}

/** First and last timestamp of the loaded record, in seconds; null while there is no data. */
function recordBounds(state: SeriesState): { firstS: number; lastS: number } | null {
  if (state.status !== "ready" || state.series.length === 0) {
    return null;
  }
  const timeAxis = toUplotData(state.series)[0];
  if (timeAxis.length === 0 || timeAxis[0] === null || timeAxis[timeAxis.length - 1] === null) {
    return null;
  }
  return { firstS: timeAxis[0] as number, lastS: timeAxis[timeAxis.length - 1] as number };
}

/**
 * Free window chooser for the tuning page.
 *
 * Shows the PV and OUT trends of the loop. The user can either zoom them and
 * take the visible stretch, or type the start and end in minutes. The chosen
 * window is reported in seconds since the first sample, the convention all
 * analysis endpoints use.
 */
export function WindowPicker({
  datasetId,
  loop,
  window,
  onSelectWindow,
  t,
}: {
  datasetId: string;
  loop: LoopSummary;
  /** Currently chosen window, in seconds since the first sample, or null. */
  window: { startS: number; endS: number } | null;
  onSelectWindow: (w: { startS: number; endS: number }) => void;
  t: Translate;
}) {
  const seriesState = useLoopSeries(datasetId, loop);
  const [visible, setVisible] = useState<VisibleRange | null>(null);

  const bounds = useMemo(() => recordBounds(seriesState), [seriesState]);
  const recordS = bounds === null ? 0 : bounds.lastS - bounds.firstS;

  const xRange = useMemo<readonly [number, number] | null>(() => {
    if (seriesState.status !== "ready" || window === null) {
      return null;
    }
    return windowToRange(toUplotData(seriesState.series)[0], [window.startS, window.endS]);
  }, [seriesState, window?.startS, window?.endS]);

  const inputs = useMinuteInputs(window, recordS, onSelectWindow);

  const useVisibleRange = () => {
    if (visible === null || bounds === null) {
      return;
    }
    const relative = { startS: visible[0] - bounds.firstS, endS: visible[1] - bounds.firstS };
    onSelectWindow(clampWindow(relative, recordS));
  };

  return (
    <section className="window-picker" aria-labelledby="window-picker-title">
      <h3 id="window-picker-title">{t("tuning.window.pickTitle")}</h3>

      <WindowTrends
        state={seriesState}
        loop={loop}
        t={t}
        xRange={xRange}
        onZoom={(minSeconds, maxSeconds) =>
          setVisible((old) => (old && old[0] === minSeconds && old[1] === maxSeconds ? old : [minSeconds, maxSeconds]))
        }
      />

      <p className="hint">{t("tuning.window.zoomHint")}</p>
      <button
        type="button"
        className="filter-chip"
        disabled={visible === null || bounds === null}
        onClick={useVisibleRange}
      >
        {t("tuning.window.useVisible")}
      </button>

      <div className="window-picker-inputs">
        <MinuteField
          label={t("tuning.window.startMin")}
          value={inputs.startText}
          onChange={inputs.setStartText}
        />
        <MinuteField
          label={t("tuning.window.endMin")}
          value={inputs.endText}
          onChange={inputs.setEndText}
        />
        <button type="button" className="filter-chip" disabled={!inputs.canApply} onClick={inputs.apply}>
          {t("tuning.window.apply")}
        </button>
      </div>

      {inputs.isInvalid && (
        <p role="alert">{t("tuning.window.invalid")}</p>
      )}
    </section>
  );
}

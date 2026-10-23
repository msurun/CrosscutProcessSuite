// src/components/TrendPane.tsx
// A synced uPlot time-series pane: role-labelled legend that shows the last value when not hovering,
// a shaded MODE band, range buttons and an undo of the last range change.
import { useCallback, useEffect, useRef, useState } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import { formatFixed } from "../format";
import type { Translate } from "../findings";
import { fittingPresets, modeSpans, presetRange, type RangePreset, type TimeSpan } from "../trendData";
import { visibleRange } from "../visibleRange";

/** Minimum pixel width for the chart so uPlot never renders a degenerate canvas. */
const MIN_WIDTH_PX = 300;
/** Default height in pixels. */
const DEFAULT_HEIGHT_PX = 180;
/** Default cursor sync key: panes sharing it show the same crosshair. */
const DEFAULT_SYNC_KEY = "crosscut";
/** Stroke width of the value series lines, in pixels. */
const SERIES_STROKE_WIDTH = 1.5;
/** Diameter of a marker-only point, in pixels. */
const MARKER_SIZE_PX = 8;

export interface TrendPaneProps {
  /** uPlot data layout: [timesInSeconds, ...seriesValues]; null values are gaps. */
  data: (number | null)[][];
  /** One label per value series, in the same order as the data columns. */
  labels: string[];
  /** One CSS variable name per value series, e.g. "--series-1". */
  colors: string[];
  /** Name of the x series in the legend (translated by the caller); defaults to "time". */
  timeLabel?: string;
  /** Optional y-axis unit shown next to the axis label. */
  unit?: string;
  /** Chart height in pixels. Defaults to 180. */
  height?: number;
  /** Panes with the same key share the crosshair. Defaults to "crosscut". */
  syncKey?: string;
  /** False draws a plain numeric x axis (e.g. seconds since the start); default true = clock time. */
  xIsTime?: boolean;
  /** Label of a numeric x axis. */
  xLabel?: string;
  /** Visible x range in seconds set from outside (e.g. a finding window); null shows everything. */
  xRange?: readonly [number, number] | null;
  /** Called with the visible x range when the user zooms. */
  onZoom?: (minSeconds: number, maxSeconds: number) => void;
  /** Translator; without it the range buttons, undo and role labels are not shown. */
  t?: Translate;
  /** One role per value series ("pv", "sp" or "out"), shown before the label in the legend. */
  roles?: SeriesRole[];
  /** MODE tag values aligned with the time column; manual stretches (0) are shaded. */
  mode?: (number | null)[];
  /** Indices (in `labels`) of series drawn as markers only, without a line (e.g. lab results). */
  markerSeries?: number[];
  /** Called with the time (seconds) under the cursor, or null when the cursor leaves the plot. */
  onCursor?: (seconds: number | null) => void;
}

/** What a value series is in the control loop. */
export type SeriesRole = "pv" | "sp" | "out";

/** Decimals of the legend values. */
const LEGEND_DECIMALS = 2;
/** Opacity of the shaded MODE band. */
const MODE_BAND_ALPHA = 0.18;
/** How many earlier ranges Undo can step back through. */
const MAX_RANGE_HISTORY = 20;

/** Translated PV/SP/OUT abbreviation. */
function roleText(t: Translate, role: SeriesRole): string {
  if (role === "pv") return t("trend.role.pv");
  if (role === "sp") return t("trend.role.sp");
  return t("trend.role.out");
}

/** Legend label of one series: "PV tag" when a role is known, else just the tag. */
function legendLabel(props: TrendPaneProps, index: number): string {
  const role = props.roles?.[index];
  return props.t && role ? `${roleText(props.t, role)} ${props.labels[index]}` : props.labels[index];
}

/** Legend value: the hovered sample, or the last sample while the cursor is away. */
function legendValue(self: uPlot, raw: number | null, seriesIndex: number, cursorIndex: number | null | undefined): string {
  const column = self.data[seriesIndex] ?? [];
  const value = cursorIndex == null ? column[column.length - 1] ?? null : raw;
  return value === null || value === undefined ? "--" : formatFixed(value, LEGEND_DECIMALS);
}

/** Hooks into the plot that the component needs: shading and range tracking. */
interface PlotCallbacks {
  spans: () => readonly TimeSpan[];
  onRange: (min: number, max: number) => void;
}

/** Paint the MODE stretches behind the series. */
function drawModeBand(self: uPlot, spans: readonly TimeSpan[], color: string): void {
  const { ctx, bbox } = self;
  ctx.save();
  ctx.globalAlpha = MODE_BAND_ALPHA;
  ctx.fillStyle = color;
  for (const [start, end] of spans) {
    const left = self.valToPos(start, "x", true);
    const right = self.valToPos(end, "x", true);
    ctx.fillRect(left, bbox.top, Math.max(right - left, 1), bbox.height);
  }
  ctx.restore();
}

/** Read a CSS custom property from the document root, trimmed. */
function readCssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Date and time as the user's language writes them, for axis ticks and the cursor readout. */
function timeFormatter(options: Intl.DateTimeFormatOptions): (seconds: number) => string {
  const locale = document.documentElement.lang || undefined;
  const format = new Intl.DateTimeFormat(locale, options);
  return (seconds) => format.format(new Date(seconds * MILLISECONDS_PER_SECOND));
}

const MILLISECONDS_PER_SECOND = 1000;
/** Minimum pixels between time ticks; a "dd.mm, hh:mm" label needs about 90. */
const TIME_TICK_SPACE_PX = 100;
const TICK_FORMAT: Intl.DateTimeFormatOptions = { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" };
const CURSOR_FORMAT: Intl.DateTimeFormatOptions = { ...TICK_FORMAT, second: "2-digit" };

/** One value series: a line, or markers only when its index is listed in `markerSeries`. */
function seriesOptions(props: TrendPaneProps, index: number): uPlot.Series {
  const stroke = readCssVar(props.colors[index]);
  const base = { label: legendLabel(props, index), value: legendValue, stroke, width: SERIES_STROKE_WIDTH, spanGaps: false };
  if (!props.markerSeries?.includes(index)) return base;
  return { ...base, paths: () => null, points: { show: true, size: MARKER_SIZE_PX, stroke, fill: stroke } };
}

/** Build the uPlot options: colours are resolved once, series come from labels/colors. */
function buildOptions(props: TrendPaneProps, width: number, callbacks: PlotCallbacks): uPlot.Options {
  const textColor = readCssVar("--text-muted");
  const gridColor = readCssVar("--grid");
  const isTime = props.xIsTime ?? true;
  const formatTick = timeFormatter(TICK_FORMAT);
  const formatCursor = timeFormatter(CURSOR_FORMAT);
  const series: uPlot.Series[] = [
    { label: props.timeLabel ?? (isTime ? "time" : (props.xLabel ?? "x")), ...(isTime ? { value: (_: uPlot, v: number | null) => (v === null ? "--" : formatCursor(v)) } : {}) },
    ...props.labels.map((_, index) => seriesOptions(props, index)),
  ];
  return {
    width,
    height: props.height ?? DEFAULT_HEIGHT_PX,
    cursor: { sync: { key: props.syncKey ?? DEFAULT_SYNC_KEY } },
    scales: { x: { time: props.xIsTime ?? true } },
    axes: [
      {
        label: props.xLabel,
        stroke: textColor,
        grid: { stroke: gridColor },
        ...(isTime ? { space: TIME_TICK_SPACE_PX, values: (_: uPlot, ticks: number[]) => ticks.map(formatTick) } : {}),
      },
      { label: props.unit, stroke: textColor, grid: { stroke: gridColor } },
    ],
    series,
    hooks: {
      setCursor: [
        (self) => {
          const index = self.cursor.idx;
          props.onCursor?.(index == null ? null : (self.data[0][index] ?? null));
        },
      ],
      drawClear: [(self) => drawModeBand(self, callbacks.spans(), textColor)],
      setScale: [
        (self, scaleKey) => {
          if (scaleKey !== "x") return;
          const range = visibleRange(self.scales.x.min, self.scales.x.max, self.data[0] ?? []);
          if (!range) return;
          callbacks.onRange(range[0], range[1]);
          props.onZoom?.(range[0], range[1]);
        },
      ],
    },
  };
}

/** Counts theme switches (the `data-theme` attribute of <html>) so the plot can re-read its colours. */
function useThemeVersion(): number {
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const observer = new MutationObserver(() => setVersion((v) => v + 1));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);
  return version;
}

/** Tracks the visible x range so the user can step back to the previous one. */
function useRangeHistory(plotRef: { current: uPlot | null }) {
  const current = useRef<TimeSpan | null>(null);
  const history = useRef<TimeSpan[]>([]);
  const [canUndo, setCanUndo] = useState(false);

  const onRange = useCallback((min: number, max: number) => {
    const before = current.current;
    current.current = [min, max];
    if (before === null || (before[0] === min && before[1] === max)) return;
    history.current = [...history.current, before].slice(-MAX_RANGE_HISTORY);
    setCanUndo(true);
  }, []);

  const reset = useCallback(() => {
    history.current = [];
    setCanUndo(false);
  }, []);

  const undo = useCallback(() => {
    const previous = history.current[history.current.length - 1];
    if (!previous) return;
    history.current = history.current.slice(0, -1);
    setCanUndo(history.current.length > 0);
    current.current = previous; // already the current range, so the scale hook does not record it again
    plotRef.current?.setScale("x", { min: previous[0], max: previous[1] });
  }, [plotRef]);

  return { onRange, reset, undo, canUndo };
}

/** The range buttons and Undo above the plot. */
function RangeToolbar(props: {
  t: Translate;
  presets: RangePreset[];
  canUndo: boolean;
  onPreset: (preset: RangePreset) => void;
  onUndo: () => void;
}) {
  return (
    <div className="trend-toolbar" role="group" aria-label={props.t("trend.range")}>
      {props.presets.map((preset) => (
        <button key={preset} type="button" onClick={() => props.onPreset(preset)}>
          {props.t(`trends.range.${preset}`)}
        </button>
      ))}
      <button type="button" onClick={props.onUndo} disabled={!props.canUndo}>
        {props.t("trends.undoZoom")}
      </button>
    </div>
  );
}

/**
 * A synced, resizable time-series pane backed by uPlot.
 * Re-creates the plot when labels, colors, height or syncKey change;
 * calls setData on data changes to avoid flicker.
 */
export function TrendPane(props: TrendPaneProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);
  const themeVersion = useThemeVersion();
  const rangeHistory = useRangeHistory(plotRef);
  const times = props.data[0] as number[];
  const spans = props.mode ? modeSpans(times, props.mode) : [];
  const spansRef = useRef<readonly TimeSpan[]>(spans);
  spansRef.current = spans;

  // Create (or re-create) the plot when structural props change.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const width = Math.max(container.clientWidth, MIN_WIDTH_PX);
    const callbacks = { spans: () => spansRef.current, onRange: rangeHistory.onRange };
    const plot = new uPlot(buildOptions(props, width, callbacks), props.data as uPlot.AlignedData, container);
    plotRef.current = plot;

    const observer = new ResizeObserver(() => {
      plot.setSize({ width: Math.max(container.clientWidth, MIN_WIDTH_PX), height: plot.height });
    });
    observer.observe(container);

    return () => {
      observer.disconnect();
      plot.destroy();
      plotRef.current = null;
    };
    // Deps intentionally exclude `data` and `unit`: those update without re-creating.
  }, [props.labels.join("|"), props.colors.join("|"), props.roles?.join("|"), props.markerSeries?.join("|"), props.height, props.syncKey, props.xIsTime, themeVersion]);

  // Push new data into the existing plot without re-creating it.
  useEffect(() => {
    plotRef.current?.setData(props.data as uPlot.AlignedData);
  }, [props.data]);

  // Follow an x range chosen outside the plot; null returns to the full extent of the data.
  // It runs after the data update because setData resets the visible range.
  useEffect(() => {
    const plot = plotRef.current;
    if (!plot) return;
    const range = props.xRange ?? (times.length > 0 ? [times[0], times[times.length - 1]] : null);
    if (range) plot.setScale("x", { min: range[0], max: range[1] });
    rangeHistory.reset();
  }, [props.xRange?.[0], props.xRange?.[1], props.data]);

  // Repaint the MODE band when the mode data changes. uPlot commits its first scales in a microtask;
  // a redraw() before that commit discards the pending scales and leaves the plot without lines, so a
  // plot that has no x scale yet is skipped (its first commit paints the band anyway).
  useEffect(() => {
    const plot = plotRef.current;
    if (plot && plot.scales.x.min != null) plot.redraw();
  }, [props.mode]);

  const showPreset = (preset: RangePreset) => {
    const range = presetRange(times, preset);
    if (range) plotRef.current?.setScale("x", { min: range[0], max: range[1] });
  };

  return (
    <div className="trend-pane">
      {props.t && (
        <RangeToolbar
          t={props.t}
          presets={fittingPresets(times)}
          canUndo={rangeHistory.canUndo}
          onPreset={showPreset}
          onUndo={rangeHistory.undo}
        />
      )}
      <div ref={containerRef} role="img" aria-label={props.labels.join(", ")} />
      {props.t && spans.length > 0 && <p className="trend-mode-note">{props.t("trend.modeBand")}</p>}
    </div>
  );
}

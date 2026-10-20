// src/components/TrendPane.tsx
import { useEffect, useRef, useState } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import { visibleRange } from "../visibleRange";

/** Minimum pixel width for the chart so uPlot never renders a degenerate canvas. */
const MIN_WIDTH_PX = 300;
/** Default height in pixels. */
const DEFAULT_HEIGHT_PX = 180;
/** Default cursor sync key: panes sharing it show the same crosshair. */
const DEFAULT_SYNC_KEY = "crosscut";
/** Stroke width of the value series lines, in pixels. */
const SERIES_STROKE_WIDTH = 1.5;

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

/** Build the uPlot options: colours are resolved once, series come from labels/colors. */
function buildOptions(props: TrendPaneProps, width: number): uPlot.Options {
  const textColor = readCssVar("--text-muted");
  const gridColor = readCssVar("--grid");
  const isTime = props.xIsTime ?? true;
  const formatTick = timeFormatter(TICK_FORMAT);
  const formatCursor = timeFormatter(CURSOR_FORMAT);
  const series: uPlot.Series[] = [
    { label: props.timeLabel ?? (isTime ? "time" : (props.xLabel ?? "x")), ...(isTime ? { value: (_: uPlot, v: number | null) => (v === null ? "--" : formatCursor(v)) } : {}) },
    ...props.labels.map((label, index) => ({
      label,
      stroke: readCssVar(props.colors[index]),
      width: SERIES_STROKE_WIDTH,
      spanGaps: false,
    })),
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
      setScale: [
        (self, scaleKey) => {
          if (scaleKey !== "x" || !props.onZoom) return;
          const range = visibleRange(self.scales.x.min, self.scales.x.max, self.data[0] ?? []);
          if (range) props.onZoom(range[0], range[1]);
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

/**
 * A synced, resizable time-series pane backed by uPlot.
 * Re-creates the plot when labels, colors, height or syncKey change;
 * calls setData on data changes to avoid flicker.
 */
export function TrendPane(props: TrendPaneProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);
  const themeVersion = useThemeVersion();

  // Create (or re-create) the plot when structural props change.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const width = Math.max(container.clientWidth, MIN_WIDTH_PX);
    const plot = new uPlot(buildOptions(props, width), props.data as uPlot.AlignedData, container);
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
  }, [props.labels.join("|"), props.colors.join("|"), props.height, props.syncKey, props.xIsTime, themeVersion]);

  // Push new data into the existing plot without re-creating it.
  useEffect(() => {
    plotRef.current?.setData(props.data as uPlot.AlignedData);
  }, [props.data]);

  // Follow an x range chosen outside the plot; null returns to the full extent of the data.
  // It runs after the data update because setData resets the visible range.
  useEffect(() => {
    const plot = plotRef.current;
    if (!plot) return;
    const times = props.data[0] as number[];
    const range = props.xRange ?? (times.length > 0 ? [times[0], times[times.length - 1]] : null);
    if (range) plot.setScale("x", { min: range[0], max: range[1] });
  }, [props.xRange?.[0], props.xRange?.[1], props.data]);

  return (
    <div
      ref={containerRef}
      className="trend-pane"
      role="img"
      aria-label={props.labels.join(", ")}
    />
  );
}

/**
 * Membership chart of one fuzzy variable: draws the terms as curves, an optional
 * value cursor with the membership degree on each curve, and a clickable legend.
 */

import type { Translate } from "../findings";
import { termLabel, variableLabel } from "../fuzzyNames";
import type { FuzzyTerm, FuzzyVariable } from "../fuzzy";
import { sampleTerm, termColor } from "../fuzzy";
import { formatSignificant } from "../format";

/** Fixed viewBox size; the SVG scales to its container, so geometry stays in these units. */
const VIEW_WIDTH = 400;
const VIEW_HEIGHT = 140;
const PLOT_LEFT = 30;
const PLOT_RIGHT = 390;
const PLOT_TOP = 10; // membership 1
const PLOT_BOTTOM = 110; // membership 0
/** Number of samples per curve; enough for a smooth shape in the fixed viewBox. */
const SAMPLE_POINTS = 121;
/** Vertical grid at membership 0, 0.5 and 1. */
const GRID_DEGREES = [0, 0.5, 1];
const DEFAULT_HEIGHT_PX = 160;
const SELECTED_STROKE_WIDTH = 2.5;
const NORMAL_STROKE_WIDTH = 1.5;
const UNSELECTED_OPACITY = 0.8;
const MARKER_RADIUS = 3;
/** A degree below this is too small to draw a marker for. */
const MIN_VISIBLE_DEGREE = 0;

export interface MembershipChartProps {
  variable: FuzzyVariable;
  value?: number | null;
  degrees?: Record<string, number>;
  selectedTerm?: string | null;
  onSelectTerm?: (name: string) => void;
  height?: number;
  /** Translator for example-system names; without it stored names are shown. */
  t?: Translate;
}

/** Map `value` from [low, high] to the plot x range, clamped to the plot area. */
function toX(value: number, low: number, high: number): number {
  const span = high - low;
  if (span === 0) return PLOT_LEFT;
  const ratio = (value - low) / span;
  return PLOT_LEFT + clamp(ratio, 0, 1) * (PLOT_RIGHT - PLOT_LEFT);
}

/** Map a membership degree from [0, 1] to the plot y range. */
function toY(degree: number): number {
  return PLOT_BOTTOM - clamp(degree, 0, 1) * (PLOT_BOTTOM - PLOT_TOP);
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value));
}

/** Format a number with at most 4 significant digits for the axis ticks. */
function formatTick(value: number): string {
  return formatSignificant(value);
}

/** Build the `points` attribute of one term curve. */
function curvePoints(term: FuzzyTerm, variable: FuzzyVariable): string {
  const x = sampleTerm(term, variable.low, variable.high, SAMPLE_POINTS).x;
  const degree = sampleTermDegree(term, variable);
  return x.map((sample, index) => `${toX(sample, variable.low, variable.high)},${toY(degree[index])}`).join(" ");
}

/** Sample the membership curve of `term` over the variable range. */
function sampleTermDegree(term: FuzzyTerm, variable: FuzzyVariable): number[] {
  return sampleTerm(term, variable.low, variable.high, SAMPLE_POINTS).y;
}

/** True when `value` is a finite number inside [variable.low, variable.high]. */
function isInsideRange(value: number | null | undefined, variable: FuzzyVariable): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= variable.low && value <= variable.high;
}

function strokeWidthForTerm(term: FuzzyTerm, selectedTerm?: string | null): number {
  return term.name === selectedTerm ? SELECTED_STROKE_WIDTH : NORMAL_STROKE_WIDTH;
}

function opacityForTerm(term: FuzzyTerm, selectedTerm?: string | null): number {
  return selectedTerm === null || selectedTerm === undefined || term.name === selectedTerm
    ? 1
    : UNSELECTED_OPACITY;
}

/** One horizontal grid line at the given membership degree. */
function GridLine({ degree }: { degree: number }) {
  return (
    <line x1={PLOT_LEFT} y1={toY(degree)} x2={PLOT_RIGHT} y2={toY(degree)} stroke="var(--grid)" strokeWidth={1} />
  );
}

/** One term curve, clickable to select the term. */
function TermPolyline({
  term,
  index,
  variable,
  selectedTerm,
  onSelectTerm,
}: {
  term: FuzzyTerm;
  index: number;
  variable: FuzzyVariable;
  selectedTerm?: string | null;
  onSelectTerm?: (name: string) => void;
}) {
  return (
    <polyline
      fill="none"
      points={curvePoints(term, variable)}
      stroke={`var(${termColor(index)})`}
      strokeWidth={strokeWidthForTerm(term, selectedTerm)}
      opacity={opacityForTerm(term, selectedTerm)}
      vectorEffect="non-scaling-stroke"
      onClick={() => onSelectTerm?.(term.name)}
      style={{ cursor: "pointer" }}
    />
  );
}

/** Dashed cursor at the current input value. */
function ValueCursor({ x }: { x: number }) {
  return (
    <line
      x1={x}
      y1={PLOT_TOP}
      x2={x}
      y2={PLOT_BOTTOM}
      stroke="var(--text)"
      strokeDasharray="4 3"
      vectorEffect="non-scaling-stroke"
    />
  );
}

/** Marker on one curve at the cursor x, sized by the term colour. */
function DegreeMarker({ degree, index, x }: { degree: number; index: number; x: number }) {
  return <circle cx={x} cy={toY(degree)} r={MARKER_RADIUS} fill={`var(${termColor(index)})`} />;
}

/** Markers for every term whose degree is above {@link MIN_VISIBLE_DEGREE}. */
function DegreeMarkers({
  variable,
  degrees,
  cursorX,
}: {
  variable: FuzzyVariable;
  degrees: Record<string, number>;
  cursorX: number;
}) {
  return (
    <>
      {variable.terms.map((term, index) => {
        const degree = degrees[term.name] ?? 0;
        if (degree <= MIN_VISIBLE_DEGREE) return null;
        return <DegreeMarker key={term.name} degree={degree} index={index} x={cursorX} />;
      })}
    </>
  );
}

/** The three numbers under the plot: low, middle, high (HTML, so the text is not stretched). */
function AxisTicks({ low, high }: { low: number; high: number }) {
  return (
    <div className="chart-ticks">
      <span>{formatTick(low)}</span>
      <span>{formatTick((low + high) / 2)}</span>
      <span>{formatTick(high)}</span>
    </div>
  );
}

/** One legend entry: colour swatch, term name and its degree when known. */
function LegendEntry({
  term,
  index,
  degree,
  onSelectTerm,
  text,
}: {
  term: FuzzyTerm;
  index: number;
  degree?: number;
  onSelectTerm?: (name: string) => void;
  text: string;
}) {
  const color = termColor(index);
  return (
    <li>
      <span className="legend-swatch" style={{ background: `var(${color})` }} />
      <button type="button" className="link-button" onClick={() => onSelectTerm?.(term.name)}>
        {text}
      </button>
      {degree !== undefined ? ` ${Math.round(degree * 100)} %` : null}
    </li>
  );
}

/** Legend rows of every term, with the degree percentage when degrees are given. */
function ChartLegend({
  variable,
  degrees,
  onSelectTerm,
  t,
}: {
  variable: FuzzyVariable;
  degrees?: Record<string, number>;
  onSelectTerm?: (name: string) => void;
  t?: Translate;
}) {
  return (
    <ul className="chart-legend">
      {variable.terms.map((term, index) => (
        <LegendEntry
          key={term.name}
          term={term}
          index={index}
          degree={degrees?.[term.name]}
          onSelectTerm={onSelectTerm}
          text={t === undefined ? term.name : termLabel(t, variable.id, term.name)}
        />
      ))}
    </ul>
  );
}

/** The value cursor and, when degrees are known, their markers on the curves. */
function CursorLayer({ variable, degrees, cursorX }: { variable: FuzzyVariable; degrees?: Record<string, number>; cursorX: number }) {
  return (
    <>
      <ValueCursor x={cursorX} />
      {degrees ? <DegreeMarkers variable={variable} degrees={degrees} cursorX={cursorX} /> : null}
    </>
  );
}

/** Draw the membership functions of one variable, with an optional live input value. */
export function MembershipChart({
  variable,
  value,
  degrees,
  selectedTerm,
  onSelectTerm,
  height,
  t,
}: MembershipChartProps) {
  const showCursor = isInsideRange(value, variable);
  const cursorX = showCursor ? toX(value, variable.low, variable.high) : PLOT_LEFT;
  return (
    <figure className="membership-chart">
      <svg
        viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
        preserveAspectRatio="none"
        style={{ width: "100%", height: height ?? DEFAULT_HEIGHT_PX }}
        role="img"
        aria-label={t === undefined ? (variable.label ?? variable.id) : variableLabel(t, variable)}
      >
        {GRID_DEGREES.map((degree) => (
          <GridLine key={degree} degree={degree} />
        ))}
        {variable.terms.map((term, index) => (
          <TermPolyline
            key={term.name}
            term={term}
            index={index}
            variable={variable}
            selectedTerm={selectedTerm}
            onSelectTerm={onSelectTerm}
          />
        ))}
        {showCursor ? <CursorLayer variable={variable} degrees={degrees} cursorX={cursorX} /> : null}
      </svg>
        <AxisTicks low={variable.low} high={variable.high} />
      <ChartLegend variable={variable} degrees={degrees} onSelectTerm={onSelectTerm} t={t} />
    </figure>
  );
}

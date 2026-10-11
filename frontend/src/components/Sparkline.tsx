// src/components/Sparkline.tsx

/** Width of the SVG viewBox in user units. */
const VIEWBOX_WIDTH = 100;
/** Height of the SVG viewBox in user units. */
const VIEWBOX_HEIGHT = 24;
/** Vertical padding kept above and below the drawn line, in user units. */
const VERTICAL_PADDING = 2;
/** Y coordinate of the flat line drawn when every value is identical. */
const FLAT_LINE_Y = 12;
/** Width in user units of the segment drawn for a run of a single value. */
const SINGLE_POINT_WIDTH = 1;
/** Number of decimals used in the "points" attribute. */
const COORDINATE_DECIMALS = 2;

/** A series of values where `null` means "no measurement here". */
export type SparklineValues = (number | null)[];

/**
 * Splits the values into consecutive runs of non-null numbers.
 *
 * Returns one array per run, each entry carrying the value and its index in
 * the original array, so the caller can still place it on the x axis.
 */
function toRuns(values: SparklineValues): { index: number; value: number }[][] {
  const runs: { index: number; value: number }[][] = [];
  let currentRun: { index: number; value: number }[] = [];

  values.forEach((value, index) => {
    if (value === null || Number.isNaN(value)) {
      if (currentRun.length > 0) {
        runs.push(currentRun);
        currentRun = [];
      }
      return;
    }
    currentRun.push({ index, value });
  });

  if (currentRun.length > 0) {
    runs.push(currentRun);
  }
  return runs;
}

/** Returns the lowest and highest non-null values, or null when there are none. */
function findExtent(values: SparklineValues): { minimum: number; maximum: number } | null {
  const numbers = values.filter((value): value is number => value !== null && !Number.isNaN(value));
  if (numbers.length === 0) {
    return null;
  }
  return { minimum: Math.min(...numbers), maximum: Math.max(...numbers) };
}

/** Maps an array index to an x coordinate spread over the full viewBox width. */
function toXCoordinate(index: number, lastIndex: number): number {
  if (lastIndex === 0) {
    return 0;
  }
  return (index / lastIndex) * VIEWBOX_WIDTH;
}

/** Maps a value to a y coordinate; higher values sit closer to the top. */
function toYCoordinate(value: number, minimum: number, maximum: number): number {
  if (maximum === minimum) {
    return FLAT_LINE_Y;
  }
  const drawableHeight = VIEWBOX_HEIGHT - VERTICAL_PADDING * 2;
  const normalised = (value - minimum) / (maximum - minimum);
  return VIEWBOX_HEIGHT - VERTICAL_PADDING - normalised * drawableHeight;
}

/**
 * Formats one run as the "points" attribute of an SVG polyline.
 *
 * A run of a single value has no length, so it becomes a short horizontal
 * segment of `SINGLE_POINT_WIDTH` user units so the point stays visible.
 */
function toPointString(run: { index: number; value: number }[], extent: { minimum: number; maximum: number }, lastIndex: number): string {
  const y = toYCoordinate(run[0].value, extent.minimum, extent.maximum);
  if (run.length === 1) {
    const x = toXCoordinate(run[0].index, lastIndex);
    const left = Math.min(x, VIEWBOX_WIDTH - SINGLE_POINT_WIDTH);
    return `${left.toFixed(COORDINATE_DECIMALS)},${y.toFixed(COORDINATE_DECIMALS)} ${(left + SINGLE_POINT_WIDTH).toFixed(COORDINATE_DECIMALS)},${y.toFixed(COORDINATE_DECIMALS)}`;
  }
  return run
    .map((point) => {
      const x = toXCoordinate(point.index, lastIndex);
      const pointY = toYCoordinate(point.value, extent.minimum, extent.maximum);
      return `${x.toFixed(COORDINATE_DECIMALS)},${pointY.toFixed(COORDINATE_DECIMALS)}`;
    })
    .join(' ');
}

/**
 * Builds the `points` attribute of every polyline to draw.
 *
 * Returns one string per consecutive run of non-null values. Null values and
 * empty input produce no runs, so the result is an empty array.
 */
export function toPoints(values: SparklineValues): string[] {
  const extent = findExtent(values);
  if (extent === null) {
    return [];
  }
  const lastIndex = Math.max(values.length - 1, 0);
  return toRuns(values).map((run) => toPointString(run, extent, lastIndex));
}

/**
 * Renders a small inline trend chart for a series of possibly missing values.
 *
 * The line uses the current text colour and keeps a constant stroke width at
 * any size. Gaps (`null`) break the line into separate segments.
 */
export function Sparkline({ values, label }: { values: SparklineValues; label: string }): JSX.Element {
  const lines = toPoints(values);
  return (
    <svg
      className="sparkline"
      viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={label}
    >
      {lines.map((points) => (
        <polyline
          key={points}
          points={points}
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          vectorEffect="non-scaling-stroke"
        />
      ))}
    </svg>
  );
}

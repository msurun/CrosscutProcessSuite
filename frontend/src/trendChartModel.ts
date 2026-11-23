// Pure functions for building trend charts. Return new objects, never mutate.
// Use the draft type from trendChartsApi.ts. Schema rules are enforced.
// Every function <= 20 lines. JSDoc on every export.

import { TrendChartDraft, TrendSeries, TrendAxis } from "./trendChartsApi";

/** 8 distinct #rrggbb colours, colour-blind friendly (Okabe-Ito). */
export const SERIES_PALETTE = [
  "#000000", // black
  "#E69F00", // orange
  "#56B4E9", // sky blue
  "#009E73", // bluish green
  "#F0E442", // yellow
  "#0072B2", // blue
  "#D55E00", // vermilion
  "#CC79A7", // reddish purple
];

/** Create a new chart draft with the given name. */
export function emptyDraft(name: string): TrendChartDraft {
  return {
    name,
    shared: false,
    series: [],
    axes: [],
    window: { kind: "relative", last_s: 3600 },
    aggregation: "minmax",
  };
}

/** Add a series to the draft. */
export function addSeries(
  draft: TrendChartDraft,
  { source, tag, unit, label }: { source: string; tag: string; unit?: string; label?: string }
): { draft: TrendChartDraft; error?: string } {
  if (draft.series.length >= 24) {
    return { draft, error: "too_many_series" };
  }

  const existingSeries = draft.series.find((s) => s.source === source && s.tag === tag);
  if (existingSeries) {
    return { draft, error: "duplicate" };
  }

  const axis = findOrCreateAxis(draft, unit);
  const colour = findUnusedColour(draft);

  const newSeries: TrendSeries = {
    source,
    tag,
    label,
    colour,
    axis: axis.axis.id,
    style: "line",
  };

  const newDraft = {
    ...draft,
    series: [...draft.series, newSeries],
    axes: [...draft.axes, ...(axis.isNew ? [axis.axis] : [])],
  };

  return { draft: newDraft };
}

/** Remove a series from the draft. */
export function removeSeries(draft: TrendChartDraft, index: number): TrendChartDraft {
  if (index < 0 || index >= draft.series.length) {
    return draft;
  }

  const newSeries = draft.series.filter((_, i) => i !== index);
  const usedAxes = new Set(newSeries.map((s) => s.axis));
  const newAxes = draft.axes.filter((a) => usedAxes.has(a.id));

  return {
    ...draft,
    series: newSeries,
    axes: newAxes,
  };
}

/** Move a series to a different axis. */
export function moveSeriesToAxis(draft: TrendChartDraft, index: number, axisId: string): TrendChartDraft {
  if (index < 0 || index >= draft.series.length) {
    return draft;
  }

  const axisExists = draft.axes.some((a) => a.id === axisId);
  if (!axisExists) {
    return draft;
  }

  const newSeries = draft.series.map((s, i) => (i === index ? { ...s, axis: axisId } : s));
  const usedAxes = new Set(newSeries.map((s) => s.axis));
  const newAxes = draft.axes.filter((a) => usedAxes.has(a.id));

  return {
    ...draft,
    series: newSeries,
    axes: newAxes,
  };
}

/** Set the range of an axis. */
export function setAxisRange(
  draft: TrendChartDraft,
  axisId: string,
  min: number | null,
  max: number | null
): TrendChartDraft {
  const newAxes = draft.axes.map((a) =>
    a.id === axisId ? { ...a, min, max } : a
  );

  return {
    ...draft,
    axes: newAxes,
  };
}

/** Set the side of an axis. */
export function setAxisSide(draft: TrendChartDraft, axisId: string, side: "left" | "right"): TrendChartDraft {
  const newAxes = draft.axes.map((a) =>
    a.id === axisId ? { ...a, side } : a
  );

  return {
    ...draft,
    axes: newAxes,
  };
}

/** Find problems in the draft. */
export function draftProblems(draft: TrendChartDraft): string[] {
  const problems: string[] = [];

  if (draft.series.length === 0) {
    problems.push("no_series");
  }

  const axisIds = new Set(draft.axes.map((a) => a.id));
  const seriesAxisIds = new Set(draft.series.map((s) => s.axis));

  if (axisIds.size !== draft.axes.length) {
    problems.push("duplicate_axis");
  }

  for (const axisId of seriesAxisIds) {
    if (!axisIds.has(axisId)) {
      problems.push("unknown_axis");
    }
  }

  for (const axis of draft.axes) {
    if (axis.min != null && axis.max != null && axis.min >= axis.max) {
      problems.push("range_inverted");
    }
  }

  const panes = draft.axes.reduce((acc, axis) => {
    const pane = axis.pane || 0;
    acc[pane] = (acc[pane] || 0) + 1;
    return acc;
  }, {} as Record<number, number>);

  for (const pane in panes) {
    if (panes[pane] > 3) {
      problems.push("pane_full");
    }
  }

  return problems;
}

/** Most axes one pane may hold, as the schema and the API state. */
const MAX_AXES_PER_PANE = 3;
/** Number of stacked panes a chart may have (pane ids 0..2). */
const MAX_PANES = 3;

/** Axes per pane id, e.g. {0: 3, 1: 1}. */
function paneCounts(axes: readonly TrendAxis[]): Record<number, number> {
  const counts: Record<number, number> = {};
  for (const axis of axes) counts[axis.pane ?? 0] = (counts[axis.pane ?? 0] ?? 0) + 1;
  return counts;
}

/** First id "y1", "y2", ... not taken by an axis (ids stay unique after removals). */
function freeAxisId(axes: readonly TrendAxis[]): string {
  const taken = new Set(axes.map((a) => a.id));
  let n = 1;
  while (taken.has(`y${n}`)) n++;
  return `y${n}`;
}

/** The axis of the tag's unit, a new one in the first pane with room, or the last axis when all panes are full. */
function findOrCreateAxis(draft: TrendChartDraft, unit?: string): { axis: TrendAxis; isNew: boolean } {
  const wanted = unit ?? "";
  const existing = draft.axes.find((a) => (a.unit ?? "") === wanted);
  if (existing) return { axis: existing, isNew: false };
  const counts = paneCounts(draft.axes);
  let pane = 0;
  while (pane < MAX_PANES && (counts[pane] ?? 0) >= MAX_AXES_PER_PANE) pane++;
  if (pane === MAX_PANES) return { axis: draft.axes[draft.axes.length - 1], isNew: false };
  // Sides alternate within a pane: 1st axis left, 2nd right, 3rd left.
  const side = (counts[pane] ?? 0) % 2 === 0 ? "left" : "right";
  return { axis: { id: freeAxisId(draft.axes), side, pane, unit: wanted }, isNew: true };
}

function findUnusedColour(draft: TrendChartDraft): string {
  const usedColours = new Set(draft.series.map((s) => s.colour));
  for (const colour of SERIES_PALETTE) {
    if (!usedColours.has(colour)) {
      return colour;
    }
  }
  return SERIES_PALETTE[draft.series.length % SERIES_PALETTE.length];
}

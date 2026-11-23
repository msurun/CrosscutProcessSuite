// Tests for trendChartModel.ts. Cover every export and each error code.

import { describe, expect, test } from "vitest";
import {
  SERIES_PALETTE,
  emptyDraft,
  addSeries,
  removeSeries,
  moveSeriesToAxis,
  setAxisRange,
  setAxisSide,
  draftProblems,
} from "./trendChartModel";

describe("trendChartModel", () => {
  test("SERIES_PALETTE has 8 distinct colours", () => {
    expect(SERIES_PALETTE).toHaveLength(8);
    expect(new Set(SERIES_PALETTE).size).toBe(8);
  });

  test("emptyDraft creates a valid draft", () => {
    const draft = emptyDraft("Test Chart");
    expect(draft.name).toBe("Test Chart");
    expect(draft.shared).toBe(false);
    expect(draft.series).toHaveLength(0);
    expect(draft.axes).toHaveLength(0);
    expect(draft.window).toEqual({ kind: "relative", last_s: 3600 });
    expect(draft.aggregation).toBe("minmax");
  });

  test("addSeries adds a series and creates an axis", () => {
    const draft = emptyDraft("Test Chart");
    const { draft: newDraft } = addSeries(draft, { source: "source1", tag: "tag1", unit: "unit1" });
    expect(newDraft.series).toHaveLength(1);
    expect(newDraft.axes).toHaveLength(1);
    expect(newDraft.series[0].axis).toBe(newDraft.axes[0].id);
  });

  test("addSeries refuses when too many series", () => {
    const draft = emptyDraft("Test Chart");
    let newDraft = draft;
    for (let i = 0; i < 24; i++) {
      const { draft: updatedDraft } = addSeries(newDraft, { source: `source${i}`, tag: `tag${i}` });
      newDraft = updatedDraft;
    }
    const { draft: finalDraft, error } = addSeries(newDraft, { source: "source25", tag: "tag25" });
    expect(finalDraft).toEqual(newDraft);
    expect(error).toBe("too_many_series");
  });

  test("addSeries refuses duplicate series", () => {
    const draft = emptyDraft("Test Chart");
    const { draft: newDraft } = addSeries(draft, { source: "source1", tag: "tag1" });
    const { draft: finalDraft, error } = addSeries(newDraft, { source: "source1", tag: "tag1" });
    expect(finalDraft).toEqual(newDraft);
    expect(error).toBe("duplicate");
  });

  test("removeSeries removes a series and drops unused axes", () => {
    const draft = emptyDraft("Test Chart");
    const { draft: newDraft } = addSeries(draft, { source: "source1", tag: "tag1" });
    const finalDraft = removeSeries(newDraft, 0);
    expect(finalDraft.series).toHaveLength(0);
    expect(finalDraft.axes).toHaveLength(0);
  });

  test("moveSeriesToAxis moves a series to a different axis and drops the emptied axis", () => {
    let draft = addSeries(emptyDraft("T"), { source: "s", tag: "flow", unit: "m3/h" }).draft;
    draft = addSeries(draft, { source: "s", tag: "out", unit: "%" }).draft;
    draft = addSeries(draft, { source: "s", tag: "flow2", unit: "m3/h" }).draft;
    const moved = moveSeriesToAxis(draft, 1, "y1");
    expect(moved.series[1].axis).toBe("y1");
    expect(moved.axes.map((a) => a.id)).toEqual(["y1"]);
  });

  test("addSeries alternates sides per pane, opens a new pane and keeps ids unique", () => {
    let draft = emptyDraft("T");
    for (const unit of ["a", "b", "c", "d"]) draft = addSeries(draft, { source: "s", tag: unit, unit }).draft;
    expect(draft.axes.map((a) => [a.id, a.side, a.pane])).toEqual([
      ["y1", "left", 0], ["y2", "right", 0], ["y3", "left", 0], ["y4", "left", 1],
    ]);
    draft = removeSeries(draft, 0);
    draft = addSeries(draft, { source: "s", tag: "e", unit: "e" }).draft;
    expect(new Set(draft.axes.map((a) => a.id)).size).toBe(draft.axes.length);
  });

  test("addSeries puts a new unit on the last axis when all three panes are full", () => {
    let draft = emptyDraft("T");
    for (let i = 0; i < 10; i++) draft = addSeries(draft, { source: "s", tag: `t${i}`, unit: `u${i}` }).draft;
    expect(draft.axes).toHaveLength(9);
    expect(draft.series[9].axis).toBe(draft.axes[8].id);
  });

  test("setAxisRange sets the range of an axis", () => {
    const draft = emptyDraft("Test Chart");
    const { draft: newDraft } = addSeries(draft, { source: "source1", tag: "tag1" });
    const finalDraft = setAxisRange(newDraft, newDraft.axes[0].id, 0, 100);
    expect(finalDraft.axes[0].min).toBe(0);
    expect(finalDraft.axes[0].max).toBe(100);
  });

  test("setAxisSide sets the side of an axis", () => {
    const draft = emptyDraft("Test Chart");
    const { draft: newDraft } = addSeries(draft, { source: "source1", tag: "tag1" });
    const finalDraft = setAxisSide(newDraft, newDraft.axes[0].id, "right");
    expect(finalDraft.axes[0].side).toBe("right");
  });

  test("draftProblems finds no_series", () => {
    const draft = emptyDraft("Test Chart");
    const problems = draftProblems(draft);
    expect(problems).toContain("no_series");
  });

  test("draftProblems finds duplicate_axis", () => {
    const draft = addSeries(emptyDraft("T"), { source: "s", tag: "t", unit: "u" }).draft;
    expect(draftProblems({ ...draft, axes: [...draft.axes, draft.axes[0]] })).toContain("duplicate_axis");
  });

  test("draftProblems finds unknown_axis", () => {
    const draft = addSeries(emptyDraft("T"), { source: "s", tag: "t", unit: "u" }).draft;
    const series = [{ ...draft.series[0], axis: "nope" }];
    expect(draftProblems({ ...draft, series })).toContain("unknown_axis");
  });

  test("draftProblems finds range_inverted", () => {
    const draft = emptyDraft("Test Chart");
    const { draft: newDraft } = addSeries(draft, { source: "source1", tag: "tag1" });
    const finalDraft = setAxisRange(newDraft, newDraft.axes[0].id, 100, 0);
    const problems = draftProblems(finalDraft);
    expect(problems).toContain("range_inverted");
  });

  test("draftProblems finds pane_full", () => {
    const draft = addSeries(emptyDraft("T"), { source: "s", tag: "t", unit: "u" }).draft;
    const axes = ["y1", "y2", "y3", "y4"].map((id) => ({ id, side: "left" as const, pane: 0 }));
    expect(draftProblems({ ...draft, axes })).toContain("pane_full");
  });
});

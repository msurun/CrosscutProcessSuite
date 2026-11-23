// frontend/src/components/ChartBuilder.test.tsx
// Tests for ChartBuilder: adding, duplicates, axis/side/range edits, removing, problems and search.
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TagInfo } from "../api";
import { addSeries, emptyDraft } from "../trendChartModel";
import type { TrendChartDraft } from "../trendChartsApi";
import { ChartBuilder } from "./ChartBuilder";

const t = (key: string, vars?: Record<string, string | number>) => (vars ? `${key} ${JSON.stringify(vars)}` : key);
const tags: TagInfo[] = [
  { id: "FIC1_pv", unit: "m3/h", description: "Feed flow" },
  { id: "LIC2_pv", unit: "%", description: "Sump level" },
];

function twoSeries(): TrendChartDraft {
  let d = emptyDraft("c");
  d = addSeries(d, { source: "s", tag: "FIC1_pv", unit: "m3/h" }).draft;
  return addSeries(d, { source: "s", tag: "LIC2_pv", unit: "%" }).draft;
}

function setup(draft: TrendChartDraft) {
  const onChange = vi.fn();
  render(<ChartBuilder t={t} sourceId="s" tags={tags} draft={draft} onChange={onChange} />);
  return onChange;
}

describe("ChartBuilder", () => {
  it("adds a tag as a series", () => {
    const onChange = setup(emptyDraft("c"));
    fireEvent.click(screen.getByLabelText('chartBuilder.addTag {"tag":"FIC1_pv"}'));
    const next = onChange.mock.calls[0][0] as TrendChartDraft;
    expect(next.series[0]).toMatchObject({ source: "s", tag: "FIC1_pv" });
    expect(next.axes[0].unit).toBe("m3/h");
  });

  it("disables Add for an added tag", () => {
    setup(twoSeries());
    expect(screen.getByLabelText('chartBuilder.addTag {"tag":"FIC1_pv"}')).toBeDisabled();
  });

  it("shows the translated error when the model refuses", () => {
    const full = emptyDraft("c");
    for (let i = 0; i < 24; i++) full.series.push({ source: "x", tag: `t${i}`, axis: "y1" });
    const onChange = setup(full);
    fireEvent.click(screen.getByLabelText('chartBuilder.addTag {"tag":"FIC1_pv"}'));
    expect(screen.getByRole("status")).toHaveTextContent("chartBuilder.error.too_many_series");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("moves a series to another axis", () => {
    const onChange = setup(twoSeries());
    fireEvent.change(screen.getByLabelText('chartBuilder.axisOf {"tag":"FIC1_pv"}'), { target: { value: "y2" } });
    const next = onChange.mock.calls[0][0] as TrendChartDraft;
    expect(next.series[0].axis).toBe("y2");
  });

  it("changes the side and the range of an axis", () => {
    const onChange = setup(twoSeries());
    fireEvent.change(screen.getByLabelText('chartBuilder.sideOf {"axis":"y1"}'), { target: { value: "right" } });
    expect((onChange.mock.calls[0][0] as TrendChartDraft).axes[0].side).toBe("right");
    fireEvent.change(screen.getByLabelText('chartBuilder.minOf {"axis":"y1"}'), { target: { value: "5" } });
    expect((onChange.mock.calls[1][0] as TrendChartDraft).axes[0]).toMatchObject({ min: 5, max: null });
  });

  it("removes a series", () => {
    const onChange = setup(twoSeries());
    fireEvent.click(screen.getByLabelText('chartBuilder.removeTag {"tag":"FIC1_pv"}'));
    expect((onChange.mock.calls[0][0] as TrendChartDraft).series.map((s) => s.tag)).toEqual(["LIC2_pv"]);
  });

  it("lists translated problems", () => {
    setup(emptyDraft("c"));
    expect(screen.getByText("chartBuilder.problem.no_series")).toBeInTheDocument();
  });

  it("filters the picker by id or description", () => {
    setup(emptyDraft("c"));
    fireEvent.change(screen.getByLabelText("chartBuilder.search"), { target: { value: "sump" } });
    expect(screen.queryByText("FIC1_pv")).toBeNull();
    expect(screen.getByText("LIC2_pv")).toBeInTheDocument();
  });
});

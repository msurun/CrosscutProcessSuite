// src/components/TrendsPage.test.tsx
// Tests of the trends view: at most 3 panes with a "show more" button, and the cursor readout.
// TrendPane is replaced by a stub that exposes its onCursor callback through a button.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Series, TagInfo } from "../api";

const mocks = vi.hoisted(() => ({ fetchSeries: vi.fn() }));
vi.mock("../api", () => ({ fetchSeries: mocks.fetchSeries }));
vi.mock("./TrendPane", () => ({
  TrendPane: (props: { unit: string; onCursor: (s: number | null) => void; t?: unknown }) => (
    <div data-testid="pane" data-has-t={props.t ? "yes" : "no"}>
      {props.unit}
      <button type="button" onClick={() => props.onCursor(1)}>
        {`cursor-${props.unit}`}
      </button>
    </div>
  ),
}));

import { TrendsPage } from "./TrendsPage";

const t = (key: string, params?: Record<string, string | number>) =>
  params ? `${key}:${Object.values(params).join(",")}` : key;
const NS = 1e9;

function makeSeries(tag: string): Series {
  return { tag, downsampled: false, t: [0, NS, 2 * NS], min: [1, 2, 3], max: [1, 2, 3], mean: [10, 20, 30] };
}

function setup(units: string[]) {
  const tags: TagInfo[] = units.map((unit, i) => ({ id: `T${i}`, unit }));
  mocks.fetchSeries.mockResolvedValue({ dataset_id: "d", series: tags.map((tag) => makeSeries(tag.id)) });
  render(<TrendsPage datasetId="d" tags={tags} selectedTags={tags.map((tag) => tag.id)} t={t} />);
}

describe("TrendsPage", () => {
  beforeEach(() => mocks.fetchSeries.mockReset());

  it("shows 3 panes and a button for the rest, which reveals them", async () => {
    setup(["a", "b", "c", "d", "e"]);
    await waitFor(() => expect(screen.getAllByTestId("pane")).toHaveLength(3));
    fireEvent.click(screen.getByText("trends.showMorePanes:2"));
    expect(screen.getAllByTestId("pane")).toHaveLength(5);
    expect(screen.queryByText("trends.showMorePanes:2")).toBeNull();
  });

  it("has no button for 3 panes and passes t to the panes", async () => {
    setup(["a", "b", "c"]);
    await waitFor(() => expect(screen.getAllByTestId("pane")).toHaveLength(3));
    expect(screen.queryByText(/showMorePanes/)).toBeNull();
    expect(screen.getAllByTestId("pane")[0].dataset.hasT).toBe("yes");
  });

  it("reads every series at the cursor time", async () => {
    setup(["a", "b"]);
    await waitFor(() => expect(screen.getAllByTestId("pane")).toHaveLength(2));
    expect(screen.getByText("trends.readoutNone")).toBeTruthy();
    fireEvent.click(screen.getByText("cursor-a"));
    expect(screen.getAllByText(/20\.00|20,00/)).toHaveLength(2);
    expect(screen.queryByText("trends.readoutNone")).toBeNull();
  });
});

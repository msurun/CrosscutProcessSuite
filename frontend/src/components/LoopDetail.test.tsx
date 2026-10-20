// Unit tests for the LoopDetail trends: the panes render when the backend returns all loop tags,
// and a missing tag shows the trends error message instead of crashing the detail view.
// The trend panes are replaced by a stub (uPlot needs a real canvas), and fetchSeries is mocked.
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LoopDetail } from "./LoopDetail";
import { fetchSeries, type LoopSummary, type Series } from "../api";
import { makeLoop } from "../testFixtures";

vi.mock("../api", () => ({ fetchSeries: vi.fn() }));

// The loop-data editor has its own tests and would call the network here.
vi.mock("./KnowledgeEditor", () => ({ KnowledgeEditor: () => null }));

vi.mock("./TrendPane", () => ({
  TrendPane: ({ labels }: { labels: string[] }) => <div role="img" aria-label={labels.join(", ")} />,
}));

/** Fake translator: returns the key plus stringified params, as in the other test files. */
const t = (key: string, params?: Record<string, string | number>) =>
  key + (params ? JSON.stringify(params) : "");

/** Builds a minimal downsampled series for one tag with two points. */
function makeSeries(tag: string): Series {
  return { tag, downsampled: false, t: [0, 1], min: [1, 2], max: [1, 2], mean: [1, 2] };
}

/** Renders the detail view with no-op handlers for the loop and its tuning/benefit links. */
function renderDetail(loop: LoopSummary) {
  render(
    <LoopDetail
      datasetId="ds-1"
      loop={loop}
      t={t}
      onBack={vi.fn()}
      onOpenTuning={vi.fn()}
      onOpenBenefit={vi.fn()}
    />,
  );
}

describe("LoopDetail trends with all loop tags", () => {
  it("renders both trend panes and no error when PV, SP and OUT are returned", async () => {
    vi.mocked(fetchSeries).mockResolvedValue({
      dataset_id: "ds-1",
      series: [makeSeries("PV"), makeSeries("SP"), makeSeries("OUT")],
    });

    renderDetail(makeLoop());

    const panes = await screen.findAllByRole("img");
    expect(panes.map((pane) => pane.getAttribute("aria-label"))).toEqual(["PV, SP", "OUT"]);
    expect(screen.queryByText(/^trends\.error/)).not.toBeInTheDocument();
  });
});

describe("LoopDetail trends with a missing loop tag", () => {
  it("shows the trends error message and no panes when SP is not returned", async () => {
    vi.mocked(fetchSeries).mockResolvedValue({
      dataset_id: "ds-1",
      series: [makeSeries("PV"), makeSeries("OUT")],
    });

    renderDetail(makeLoop());

    expect(await screen.findByText(/^trends\.error\{"reason":"Series \\"SP\\" is missing/)).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "tuning.title" })).toBeInTheDocument();
  });
});

describe("LoopDetail finding links to the trend", () => {
  const oscillatingFinding = { code: "oscillating", params: { minutes: 5 }, window_s: [100, 700] as [number, number] };

  it("labels a whole-record finding's link as an example", () => {
    vi.mocked(fetchSeries).mockResolvedValue({ dataset_id: "ds-1", series: [] });

    renderDetail(makeLoop({ findings: [{ ...oscillatingFinding, window_kind: "example" }] }));

    expect(screen.getByRole("button", { name: "loops.showExampleInTrend" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "loops.showInTrend" })).not.toBeInTheDocument();
  });

  it("labels a cause finding's link with the normal trend text", () => {
    vi.mocked(fetchSeries).mockResolvedValue({ dataset_id: "ds-1", series: [] });

    renderDetail(makeLoop({ findings: [{ ...oscillatingFinding, window_kind: "cause" }] }));

    expect(screen.getByRole("button", { name: "loops.showInTrend" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "loops.showExampleInTrend" })).not.toBeInTheDocument();
  });
});

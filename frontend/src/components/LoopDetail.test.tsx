// Unit tests for the LoopDetail trends: the panes render when the backend returns all loop tags,
// and a missing tag shows the trends error message instead of crashing the detail view.
// The trend panes are replaced by a stub (uPlot needs a real canvas), and fetchSeries is mocked.
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LoopDetail } from "./LoopDetail";
import { fetchSeries, type LoopSummary, type Series } from "../api";

vi.mock("../api", () => ({ fetchSeries: vi.fn() }));

vi.mock("./TrendPane", () => ({
  TrendPane: ({ labels }: { labels: string[] }) => <div role="img" aria-label={labels.join(", ")} />,
}));

/** Fake translator: returns the key plus stringified params, as in the other test files. */
const t = (key: string, params?: Record<string, string | number>) =>
  key + (params ? JSON.stringify(params) : "");

/** Builds a LoopSummary with healthy defaults; tests override only what they need. */
function makeLoop(overrides: Partial<LoopSummary> = {}): LoopSummary {
  return {
    name: "Loop A",
    pv: "PV",
    sp: "SP",
    out: "OUT",
    mode: "AUTO",
    unit: "degC",
    status: "ok",
    health_percent: 80,
    classification: "good",
    findings: [],
    service_percent: 100,
    saturation_percent: 0,
    harris_index: 0.7,
    oscillation_period_s: null,
    stiction_verdict: "no_stiction",
    sparkline: [1, 2, 3],
    ...overrides,
  };
}

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

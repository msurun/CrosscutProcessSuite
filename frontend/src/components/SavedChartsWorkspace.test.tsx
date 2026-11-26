// Tests of the chart URL: a chart id from the route opens it, opening updates the URL, Copy link copies it.
// The API, auth and the heavy child components are mocked.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ getChart: vi.fn() }));
vi.mock("../trendChartsApi", () => ({ getChart: mocks.getChart, createChart: vi.fn(), saveChart: vi.fn() }));
vi.mock("../AuthContext", () => ({ useAuth: () => ({ status: "disabled" }), useCan: () => ({ allowed: true }) }));
vi.mock("./SavedChartsPanel", () => ({
  SavedChartsPanel: (p: { onOpen: (id: string) => void }) => <button type="button" onClick={() => p.onOpen("c2")}>pick-c2</button>,
}));
vi.mock("./SavedChartView", () => ({ SavedChartView: () => <div /> }));
vi.mock("./TrendWindowBar", () => ({ TrendWindowBar: () => <div /> }));
vi.mock("./ChartBuilder", () => ({ ChartBuilder: () => <div /> }));

import { SavedChartsWorkspace } from "./SavedChartsWorkspace";

const t = (key: string) => key;
const chart = (id: string) => ({ id, name: `Chart ${id}`, owner: "me", shared: false, series: [], axes: [], window: { kind: "relative", last_s: 60 } });

describe("SavedChartsWorkspace chart URL", () => {
  beforeEach(() => mocks.getChart.mockReset());

  it("opens the chart named by the route and reports it", async () => {
    mocks.getChart.mockResolvedValue(chart("c1"));
    const onChartChange = vi.fn();
    render(<SavedChartsWorkspace datasetId="ds" dataset={undefined} tags={[]} t={t} chartId="c1" onChartChange={onChartChange} />);
    await screen.findByRole("heading", { name: "Chart c1" });
    expect(mocks.getChart).toHaveBeenCalledWith("c1");
    expect(onChartChange).toHaveBeenCalledWith("c1");
  });

  it("updates the URL when a chart is picked in the list", async () => {
    mocks.getChart.mockResolvedValue(chart("c2"));
    const onChartChange = vi.fn();
    render(<SavedChartsWorkspace datasetId="ds" dataset={undefined} tags={[]} t={t} onChartChange={onChartChange} />);
    fireEvent.click(screen.getByText("pick-c2"));
    await waitFor(() => expect(onChartChange).toHaveBeenCalledWith("c2"));
  });

  it("copies a link to the open chart", async () => {
    mocks.getChart.mockResolvedValue(chart("c1"));
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<SavedChartsWorkspace datasetId="ds" dataset={undefined} tags={[]} t={t} chartId="c1" />);
    fireEvent.click(await screen.findByText("trendCharts.copyLink"));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(expect.stringContaining("#/d/ds/trends?chart=c1")));
    await screen.findByText("trendCharts.linkCopied");
  });
});

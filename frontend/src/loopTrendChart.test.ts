// Tests of "Open in Trends": the draft built from a loop and the chart saved through the API (mocked).
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LoopSummary, TagInfo } from "./api";

const mocks = vi.hoisted(() => ({ createChart: vi.fn() }));
vi.mock("./trendChartsApi", () => ({ createChart: mocks.createChart }));

import { loopChartDraft, openLoopChart } from "./loopTrendChart";

const loop = { name: "FIC101", pv: "FIC101.PV", sp: "FIC101.SP", out: "FIC101.OUT", mode: "FIC101.MODE" } as LoopSummary;
const tags: TagInfo[] = [{ id: "FIC101.PV", unit: "m3/h" }, { id: "FIC101.SP", unit: "m3/h" }, { id: "FIC101.OUT", unit: "%" }];

describe("loopChartDraft", () => {
  it("holds PV, SP, OUT and MODE with units from the tags", () => {
    const draft = loopChartDraft("ds1", loop, tags);
    expect(draft.name).toBe("FIC101 PV/SP/OUT");
    expect(draft.series.map((s) => s.tag)).toEqual(["FIC101.PV", "FIC101.SP", "FIC101.OUT", "FIC101.MODE"]);
    expect(draft.series.every((s) => s.source === "ds1")).toBe(true);
    expect(draft.axes.map((a) => a.unit)).toEqual(["m3/h", "%", ""]);
  });

  it("leaves MODE out when the loop has none", () => {
    expect(loopChartDraft("ds1", { ...loop, mode: "" }, tags).series).toHaveLength(3);
  });
});

describe("openLoopChart", () => {
  beforeEach(() => mocks.createChart.mockReset());

  it("saves the draft and returns the new chart id", async () => {
    mocks.createChart.mockResolvedValue({ id: "new123" });
    await expect(openLoopChart("ds1", loop, tags)).resolves.toBe("new123");
    expect(mocks.createChart.mock.calls[0][0].name).toBe("FIC101 PV/SP/OUT");
  });
});

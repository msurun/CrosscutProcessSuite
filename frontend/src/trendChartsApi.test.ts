// Tests for the trend charts client: method, URL, body and error mapping per call.
// fetch is stubbed per test; ApiError and API_PREFIX come from api.ts.

import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, API_PREFIX } from "./api";
import {
  copyChart,
  createChart,
  deleteChart,
  getChart,
  listCharts,
  saveChart,
  type ChartSummary,
  type TrendChart,
  type TrendChartDraft,
} from "./trendChartsApi";

const DRAFT: TrendChartDraft = {
  name: "New Chart",
  shared: false,
  series: [],
  axes: [],
  window: { kind: "relative", last_s: 3600 },
};

const CHART: TrendChart = {
  schema_version: 1,
  id: "abc123",
  owner: "user1",
  created_utc: "2023-01-01T00:00:00Z",
  updated_utc: "2023-01-01T00:00:00Z",
  ...DRAFT,
};

/** Stub fetch to answer with the given status and JSON body. */
function stubFetch(ok: boolean, status: number, body: unknown) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok,
    status,
    statusText: ok ? "OK" : "Error",
    json: () => Promise.resolve(body),
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("listCharts", () => {
  it("GETs the chart list and returns the summaries", async () => {
    const charts: ChartSummary[] = [
      { id: "abc123", name: "Chart 1", owner: "user1", shared: false, updated_utc: "2023-01-01T00:00:00Z", mine: true },
    ];
    const fetchMock = stubFetch(true, 200, { charts });

    const result = await listCharts();

    expect(fetchMock).toHaveBeenCalledWith(`${API_PREFIX}/trends/charts`, expect.anything());
    expect(result).toEqual({ charts });
  });
});

describe("getChart", () => {
  it("GETs one chart by encoded id and returns it", async () => {
    const fetchMock = stubFetch(true, 200, CHART);

    const result = await getChart("abc 123");

    expect(fetchMock).toHaveBeenCalledWith(`${API_PREFIX}/trends/charts/abc%20123`, expect.anything());
    expect(result).toEqual(CHART);
  });

  it("throws ApiError on 404", async () => {
    stubFetch(false, 404, { detail: "no such chart" });

    await expect(getChart("abc123")).rejects.toThrow(ApiError);
  });
});

describe("createChart", () => {
  it("POSTs the draft and returns the created chart", async () => {
    const fetchMock = stubFetch(true, 200, CHART);

    const result = await createChart(DRAFT);

    expect(fetchMock).toHaveBeenCalledWith(`${API_PREFIX}/trends/charts`, expect.objectContaining({
      method: "POST",
      body: JSON.stringify(DRAFT),
    }));
    expect(result).toEqual(CHART);
  });

  it("throws ApiError with the detail list on 422", async () => {
    stubFetch(false, 422, { detail: ["series: must have at least one item"] });

    await expect(createChart(DRAFT)).rejects.toThrow(ApiError);
  });
});

describe("saveChart", () => {
  it("PUTs the chart to its id and returns the saved chart", async () => {
    const fetchMock = stubFetch(true, 200, CHART);

    const result = await saveChart(CHART);

    expect(fetchMock).toHaveBeenCalledWith(`${API_PREFIX}/trends/charts/abc123`, expect.objectContaining({
      method: "PUT",
      body: JSON.stringify(CHART),
    }));
    expect(result).toEqual(CHART);
  });

  it("throws ApiError on 403", async () => {
    stubFetch(false, 403, { detail: "only the owner changes a chart" });

    await expect(saveChart(CHART)).rejects.toThrow(ApiError);
  });
});

describe("deleteChart", () => {
  it("DELETEs the chart and returns the deleted id", async () => {
    const fetchMock = stubFetch(true, 200, { deleted: "abc123" });

    const result = await deleteChart("abc123");

    expect(fetchMock).toHaveBeenCalledWith(`${API_PREFIX}/trends/charts/abc123`, expect.objectContaining({
      method: "DELETE",
    }));
    expect(result).toEqual({ deleted: "abc123" });
  });

  it("throws ApiError on 404", async () => {
    stubFetch(false, 404, { detail: "no such chart" });

    await expect(deleteChart("abc123")).rejects.toThrow(ApiError);
  });
});

describe("copyChart", () => {
  it("POSTs to the copy route and returns the copied chart", async () => {
    const copied: TrendChart = { ...CHART, id: "def456", name: "Chart 1 (copy)" };
    const fetchMock = stubFetch(true, 200, copied);

    const result = await copyChart("abc123");

    expect(fetchMock).toHaveBeenCalledWith(`${API_PREFIX}/trends/charts/abc123/copy`, expect.objectContaining({
      method: "POST",
    }));
    expect(result).toEqual(copied);
  });

  it("throws ApiError on 403", async () => {
    stubFetch(false, 403, { detail: "sharing a chart needs config.edit" });

    await expect(copyChart("abc123")).rejects.toThrow(ApiError);
  });
});

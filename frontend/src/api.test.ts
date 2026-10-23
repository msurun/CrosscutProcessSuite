// src/api.test.ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, fetchDatasets, fetchSeries, fetchTags, fetchTuning } from "./api";

/** Minimal stand-in for a fetch Response; only what src/api.ts reads. */
function fakeResponse(body: unknown, { ok = true, status = 200, statusText = "OK" } = {}) {
  return {
    ok,
    status,
    statusText,
    json: async () => body,
  };
}

/** Installs a fetch mock that replays one response and returns the mock for assertions. */
function stubFetchOnce(response: unknown): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchDatasets", () => {
  it("returns the parsed JSON", async () => {
    const datasets = [{ id: "ds-1", name: "Wind farm" }];
    stubFetchOnce(fakeResponse(datasets));

    const result = await fetchDatasets();

    expect(result).toEqual(datasets);
  });
});

describe("fetchTags", () => {
  it("requests the tags endpoint of the given dataset", async () => {
    const fetchMock = stubFetchOnce(fakeResponse([]));

    await fetchTags("ds-1");

    expect(fetchMock).toHaveBeenCalledWith("/api/datasets/ds-1/tags");
  });
});

describe("fetchSeries", () => {
  it("repeats the tag parameter and URL-encodes tag ids containing '/' or spaces", async () => {
    const fetchMock = stubFetchOnce(fakeResponse([]));

    await fetchSeries("ds-1", ["a/b", "c d"]);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/datasets/ds-1/series?tag=a%2Fb&tag=c+d",
    );
  });

  it("omits start, end and max_points when not given", async () => {
    const fetchMock = stubFetchOnce(fakeResponse([]));

    await fetchSeries("ds-1", ["a"]);

    expect(fetchMock).toHaveBeenCalledWith("/api/datasets/ds-1/series?tag=a");
  });

  it("includes start, end and max_points when given", async () => {
    const fetchMock = stubFetchOnce(fakeResponse([]));

    await fetchSeries("ds-1", ["a"], { startNs: 10, endNs: 20, maxPoints: 5 });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/datasets/ds-1/series?tag=a&start=10&end=20&max_points=5",
    );
  });

  it("rejects with an ApiError when the server answers 404 with a detail message", async () => {
    const errorBody = { detail: "unknown tag: x" };
    stubFetchOnce(fakeResponse(errorBody, { ok: false, status: 404, statusText: "Not Found" }));

    const error = await fetchSeries("ds-1", ["x"]).catch((caught) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(404);
    expect(error.message).toBe("unknown tag: x");
  });

  it("falls back to statusText when the error body is not JSON", async () => {
    const nonJsonResponse = {
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      json: async () => {
        throw new SyntaxError("Unexpected token");
      },
    };
    stubFetchOnce(nonJsonResponse);

    const error = await fetchSeries("ds-1", ["a"]).catch((caught) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(500);
    expect(error.message).toBe("Internal Server Error");
  });
});

describe("fetchTuning", () => {
  it("sends max_swing and load_step_pct together", async () => {
    const fetchMock = stubFetchOnce(fakeResponse({}));

    await fetchTuning("d", "L", { robustness: 0.5, maxSwing: 2, loadStepPct: 4 });

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("max_swing=2");
    expect(url).toContain("load_step_pct=4");
  });

  it("passes the dead-time range of an integrating model through", async () => {
    const model = { kind: "ipdt", delay_s: 5, delay_lower_s: 3, delay_upper_s: 12, delay_used_s: 12 };
    stubFetchOnce(fakeResponse({ model }));

    const payload = await fetchTuning("d", "L");

    expect(payload.model).toMatchObject({ delay_lower_s: 3, delay_upper_s: 12, delay_used_s: 12 });
  });

  it("leaves both out when one of them is missing", async () => {
    const fetchMock = stubFetchOnce(fakeResponse({}));

    await fetchTuning("d", "L", { maxSwing: 2 });

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).not.toContain("max_swing");
    expect(url).not.toContain("load_step_pct");
  });
});

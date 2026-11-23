// Tests for the sources client: URL building, the 404-as-empty catalogue rule and error mapping.
// fetch is stubbed per test, like in trendChartsApi.test.ts.
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, API_PREFIX } from "./api";
import { fetchSiteTags, listSources, loadHistory } from "./sourcesApi";

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

describe("listSources", () => {
  it("GETs /sources", async () => {
    const body = { sources: [{ id: "pi", driver: "pi" }] };
    const fetchMock = stubFetch(true, 200, body);
    expect(await listSources()).toEqual(body);
    expect(fetchMock).toHaveBeenCalledWith(`${API_PREFIX}/sources`, expect.anything());
  });
});

describe("fetchSiteTags", () => {
  it("returns the tags of the site document", async () => {
    stubFetch(true, 200, { tags: [{ id: "T1", source: "pi" }] });
    expect(await fetchSiteTags()).toEqual([{ id: "T1", source: "pi" }]);
  });

  it("returns [] on 404 (no catalogue)", async () => {
    stubFetch(false, 404, { detail: "no site" });
    expect(await fetchSiteTags()).toEqual([]);
  });

  it("rethrows other errors", async () => {
    stubFetch(false, 500, { detail: "boom" });
    await expect(fetchSiteTags()).rejects.toThrow(ApiError);
  });
});

describe("loadHistory", () => {
  const result = { dataset_id: "d1", cached: false, time_range: { start_utc: "a", end_utc: "b" }, tags: ["T1"] };

  it("builds the query with repeated tags and period_s", async () => {
    const fetchMock = stubFetch(true, 200, result);
    expect(await loadHistory("pi 1", ["T1", "T2"], { start_utc: "2026-01-01T00:00:00.000Z", end_utc: "2026-01-02T00:00:00.000Z" }, 60)).toEqual(result);
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain(`${API_PREFIX}/sources/pi%201/history?`);
    expect(url).toContain("tag=T1&tag=T2");
    expect(url).toContain("period_s=60");
  });

  it("omits period_s when raw", async () => {
    const fetchMock = stubFetch(true, 200, result);
    await loadHistory("pi", ["T1"], { start_utc: "s", end_utc: "e" });
    expect(String(fetchMock.mock.calls[0][0])).not.toContain("period_s");
  });

  it("throws ApiError with the server detail", async () => {
    stubFetch(false, 502, { detail: "source down" });
    await expect(loadHistory("pi", ["T1"], { start_utc: "s", end_utc: "e" })).rejects.toThrow("source down");
  });
});

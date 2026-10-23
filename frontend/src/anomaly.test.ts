// Tests of the pure helpers of the Anomalies page and of the anomaly API functions (fetch mocked).
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  fetchAnomalyConfig,
  fetchAnomalyIds,
  fetchAnomalyModel,
  fitAnomalyModel,
  saveAnomalyConfig,
  scanAnomalies,
  type AnomalyConfig,
  type AnomalyEvent,
} from "./api";
import { anomalyErrorCode, defaultTrainHours, eventMask, eventRows, recordHours, topShares, validateWindow } from "./anomaly";
import en from "./locales/en.json";
import pl from "./locales/pl.json";
import es from "./locales/es.json";

afterEach(() => vi.unstubAllGlobals());

function stubFetch(body: unknown, status = 200) {
  const mock = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", mock);
  return mock;
}

const CONFIG: AnomalyConfig = { schema_version: "1.0.0", id: "mc", tags: ["a", "b", "c"], mode: "advisory" };

describe("api functions", () => {
  it("lists and reads configs under /api/anomaly", async () => {
    const mock = stubFetch(["mc"]);
    expect(await fetchAnomalyIds()).toEqual(["mc"]);
    expect(mock.mock.calls[0][0]).toBe("/api/anomaly");
    stubFetch(CONFIG);
    expect(await fetchAnomalyConfig("m c")).toEqual(CONFIG);
  });

  it("PUTs a config to its own id", async () => {
    const mock = stubFetch(CONFIG);
    await saveAnomalyConfig(CONFIG);
    expect(mock.mock.calls[0][0]).toBe("/api/anomaly/mc");
    expect(mock.mock.calls[0][1].method).toBe("PUT");
    expect(JSON.parse(mock.mock.calls[0][1].body)).toEqual(CONFIG);
  });

  it("posts fit and scan windows as start_s / end_s", async () => {
    let mock = stubFetch({ k: 3 });
    await fitAnomalyModel("ds 1", "mc", { startS: 0, endS: 3600 });
    expect(mock.mock.calls[0][0]).toBe("/api/datasets/ds%201/anomaly/mc/fit");
    expect(JSON.parse(mock.mock.calls[0][1].body)).toEqual({ start_s: 0, end_s: 3600 });
    mock = stubFetch({ events: [] });
    await scanAnomalies("ds", "mc", {}, 500);
    expect(mock.mock.calls[0][0]).toBe("/api/datasets/ds/anomaly/mc/scan");
    expect(JSON.parse(mock.mock.calls[0][1].body)).toEqual({ start_s: null, end_s: null, max_points: 500 });
  });

  it("reads the model and raises ApiError with the detail on 404", async () => {
    stubFetch({ detail: "model not fitted: mc" }, 404);
    const failure = await fetchAnomalyModel("mc").catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect(anomalyErrorCode(failure)).toBe("notFitted");
  });
});

describe("error codes", () => {
  it("recognises stale and unknown tags, and nothing else", () => {
    expect(anomalyErrorCode(new ApiError(422, "tags: model is stale, fit it again"))).toBe("stale");
    expect(anomalyErrorCode(new ApiError(404, "unknown tags: ['x']"))).toBe("unknownTag");
    expect(anomalyErrorCode(new ApiError(500, "boom"))).toBeNull();
    expect(anomalyErrorCode(new Error("model not fitted"))).toBeNull();
  });

  it("has a message for every code in all three languages", () => {
    for (const catalogue of [en, pl, es] as Record<string, string>[]) {
      for (const code of ["notFitted", "stale", "unknownTag"]) expect(catalogue[`anomaly.error.${code}`]).toBeTruthy();
    }
  });
});

describe("window validation", () => {
  it("accepts hours and converts to seconds (comma allowed)", () => {
    expect(validateWindow("0", "1,5", 8)).toEqual({ ok: true, startS: 0, endS: 5400 });
  });
  it("rejects text, negatives, reversed and beyond-the-record windows", () => {
    expect(validateWindow("a", "1", 8)).toEqual({ ok: false, error: "notNumber" });
    expect(validateWindow("", "1", 8)).toEqual({ ok: false, error: "notNumber" });
    expect(validateWindow("-1", "1", 8)).toEqual({ ok: false, error: "negative" });
    expect(validateWindow("2", "2", 8)).toEqual({ ok: false, error: "order" });
    expect(validateWindow("9", "10", 8)).toEqual({ ok: false, error: "beyond" });
  });
  it("defaults to half of the whole hours, at most 24 and at least 0.5", () => {
    expect(defaultTrainHours(8)).toBe(4);
    expect(defaultTrainHours(100)).toBe(24);
    expect(defaultTrainHours(0.4)).toBe(0.5);
    expect(defaultTrainHours(null)).toBe(1);
  });
  it("reads the record length from ISO times", () => {
    expect(recordHours("2026-01-01T00:00:00Z", "2026-01-01T08:00:00Z")).toBe(8);
    expect(recordHours("x", "y")).toBeNull();
  });
});

const EVENT: AnomalyEvent = {
  start_index: 10, end_index: 20, start_s: 600, end_s: 1200, closed: true, peak_t2: 30, peak_spe: 5, peak_index: 15,
  top_spe_tags: ["a"], top_t2_tags: ["b"], exceeded: "both", n_samples: 11,
  contributions: { spe: { a: 0.6, b: 0.3, c: 0.1 }, t2: { a: 0.2, b: 0.5, c: 0.3 } },
};

describe("events", () => {
  it("computes duration and ratios of the limits", () => {
    expect(eventRows([EVENT], 15, 10)[0]).toMatchObject({ durationS: 600, t2Ratio: 2, speRatio: 0.5, closed: true });
  });
  it("masks event times with 0 and the rest with 1", () => {
    expect(eventMask([0, 600, 900, 1300], [EVENT])).toEqual([1, 0, 0, 1]);
  });
  it("ranks shares and cuts to the count", () => {
    expect(topShares(EVENT.contributions.t2, 2)).toEqual([["b", 0.5], ["c", 0.3]]);
  });
});

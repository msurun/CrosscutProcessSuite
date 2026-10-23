// Tests of the soft sensor API functions with fetch mocked: URLs, methods, bodies, id encoding and
// the error carrying the server's message.
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  fetchSoftSensorConfig,
  fetchSoftSensorIds,
  fetchSoftSensorLab,
  fetchSoftSensorModel,
  fitSoftSensor,
  runSoftSensor,
  saveSoftSensorConfig,
  uploadSoftSensorLab,
  type SoftSensorConfig,
} from "./api";

const CONFIG: SoftSensorConfig = { schema_version: "1.0.0", id: "s 1", target_tag: "lab.q", input_tags: ["a"], mode: "advisory" };

function mockFetch(body: unknown, status = 200) {
  const mock = vi.fn(() => Promise.resolve(new Response(JSON.stringify(body), { status })));
  vi.stubGlobal("fetch", mock);
  return mock;
}

/** The URL, method and parsed body of the first call. */
function firstCall(mock: ReturnType<typeof mockFetch>) {
  const [url, init] = mock.mock.calls[0] as unknown as [string, RequestInit | undefined];
  return { url, method: init?.method ?? "GET", body: init?.body ? JSON.parse(String(init.body)) : undefined };
}

afterEach(() => vi.unstubAllGlobals());

describe("soft sensor api", () => {
  it("lists ids and reads a config", async () => {
    let mock = mockFetch(["a", "b"]);
    expect(await fetchSoftSensorIds()).toEqual(["a", "b"]);
    expect(firstCall(mock)).toMatchObject({ url: "/api/softsensor", method: "GET" });
    mock = mockFetch(CONFIG);
    await fetchSoftSensorConfig("s 1");
    expect(firstCall(mock).url).toBe("/api/softsensor/s%201");
  });

  it("saves a config with PUT", async () => {
    const mock = mockFetch(CONFIG);
    await saveSoftSensorConfig(CONFIG);
    expect(firstCall(mock)).toEqual({ url: "/api/softsensor/s%201", method: "PUT", body: CONFIG });
  });

  it("uploads lab text with and without an origin", async () => {
    let mock = mockFetch({ count: 1, first_s: 0, last_s: 0, rows: [] });
    await uploadSoftSensorLab("s1", { csvText: "sample_time,value\n0,1", originIso: "2026-01-01T00:00:00Z" });
    expect(firstCall(mock)).toEqual({
      url: "/api/softsensor/s1/lab",
      method: "POST",
      body: { csv_text: "sample_time,value\n0,1", origin_iso: "2026-01-01T00:00:00Z" },
    });
    mock = mockFetch({ count: 1, first_s: 0, last_s: 0, rows: [] });
    await uploadSoftSensorLab("s1", { csvText: "x", originIso: "" });
    expect(firstCall(mock).body).toEqual({ csv_text: "x" });
  });

  it("reads the lab and the model", async () => {
    let mock = mockFetch({ count: 0 });
    await fetchSoftSensorLab("s1");
    expect(firstCall(mock).url).toBe("/api/softsensor/s1/lab");
    mock = mockFetch({});
    await fetchSoftSensorModel("s1");
    expect(firstCall(mock).url).toBe("/api/softsensor/s1/model");
  });

  it("fits with and without a train end", async () => {
    let mock = mockFetch({});
    await fitSoftSensor("ds/1", "s1", 16200);
    expect(firstCall(mock)).toEqual({ url: "/api/datasets/ds%2F1/softsensor/s1/fit", method: "POST", body: { train_end_s: 16200 } });
    mock = mockFetch({});
    await fitSoftSensor("ds", "s1");
    expect(firstCall(mock).body).toEqual({});
  });

  it("runs over a window with a point limit", async () => {
    const mock = mockFetch({});
    await runSoftSensor("ds", "s1", { startS: 0, endS: 3600 }, 500);
    expect(firstCall(mock)).toEqual({
      url: "/api/datasets/ds/softsensor/s1/run",
      method: "POST",
      body: { start_s: 0, end_s: 3600, max_points: 500 },
    });
  });

  it("raises an ApiError with the server's detail", async () => {
    mockFetch({ detail: "line 2: bad value 'x'" }, 422);
    const failure = await uploadSoftSensorLab("s1", { csvText: "x" }).catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure).toMatchObject({ status: 422, message: "line 2: bad value 'x'" });
  });
});

// Tests of the step analyzer client (see stepAnalyzer.ts): the pure logbook parser, the
// parameter/verdict formatting helpers and the fetch-based call with the global fetch mocked.
// No network is touched; replies are built as Response objects, errors as thrown Errors.
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  analyzeSteps, paramText, parseLogbook, verdictClass,
  type StepRow,
} from "./stepAnalyzer";

afterEach(() => vi.unstubAllGlobals());

/** Stub the global fetch with a reply of the given status and JSON body; return the mock. */
function reply(status: number, body: unknown) {
  const mock = vi.fn(() => Promise.resolve(new Response(JSON.stringify(body), { status })));
  vi.stubGlobal("fetch", mock);
  return mock;
}

describe("parseLogbook", () => {
  it("reads a space-separated line without seconds and shifts it by the offset", () => {
    const entries = parseLogbook("2026-10-09 12:05 text", -3);
    expect(entries).toEqual([{ time_utc: "2026-10-09T15:05:00.000Z", text: "text" }]);
  });

  it("reads an ISO line with a T and seconds", () => {
    const entries = parseLogbook("2026-10-09T12:05:30 text", 0);
    expect(entries).toEqual([{ time_utc: "2026-10-09T12:05:30.000Z", text: "text" }]);
  });

  it("reads a space-separated line with seconds", () => {
    const entries = parseLogbook("2026-10-09 12:05:45 text", 0);
    expect(entries).toEqual([{ time_utc: "2026-10-09T12:05:45.000Z", text: "text" }]);
  });

  it("turns a positive offset into an earlier UTC instant", () => {
    const entries = parseLogbook("2026-10-09 12:05 text", 2);
    expect(entries[0].time_utc).toBe("2026-10-09T10:05:00.000Z");
  });

  it("skips unreadable and empty lines", () => {
    const entries = parseLogbook("not a logbook line\n\n2026-10-09 12:05 real", 0);
    expect(entries).toHaveLength(1);
    expect(entries[0].text).toBe("real");
  });

  it("keeps inner spaces of the description", () => {
    const entries = parseLogbook("2026-10-09 12:05 pump   stopped  twice  ", 0);
    expect(entries[0].text).toBe("pump   stopped  twice");
  });
});

describe("paramText", () => {
  it("formats a value and its standard error", () => {
    expect(paramText({ value: 1.234, se: 0.056 })).toBe("1.23 \u00B1 0.06");
  });

  it("formats a value without a standard error", () => {
    expect(paramText({ value: 1.234, se: null })).toBe("1.23");
  });

  it("uses the en dash for an undefined parameter", () => {
    expect(paramText(undefined)).toBe("\u2013");
  });

  it("uses the en dash for a null value", () => {
    expect(paramText({ value: null, se: 0.05 })).toBe("\u2013");
  });

  it("uses the digits argument", () => {
    expect(paramText({ value: 1.23456, se: 0.00001 }, 4)).toBe("1.2346 \u00B1 0.0000");
  });
});

describe("verdictClass", () => {
  it("maps ok to ok", () => {
    expect(verdictClass("ok")).toBe("ok");
  });

  it("maps weak to a warning", () => {
    expect(verdictClass("weak")).toBe("warning");
  });

  it("maps unusable to a problem", () => {
    expect(verdictClass("unusable")).toBe("problem");
  });
});

describe("analyzeSteps", () => {
  it("posts the loop to the encoded dataset endpoint and parses the reply", async () => {
    const payload = { loop: "LIC-101", rows: [], skipped: [] };
    const mock = reply(200, payload);
    const result = await analyzeSteps("run/1", { loop: "LIC-101" });
    expect(result).toEqual(payload);
    const [url, init] = mock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/datasets/run%2F1/steps");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body as string)).toEqual({ model: "auto", logbook: [], loop: "LIC-101" });
  });

  it("sends the model and logbook when given", async () => {
    const mock = reply(200, { loop: "LIC-101", rows: [], skipped: [] });
    const logbook = [{ time_utc: "2026-10-09T15:05:00.000Z", text: "step" }];
    await analyzeSteps("run1", { loop: "LIC-101", model: "fopdt", logbook });
    const [, init] = mock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ model: "fopdt", logbook, loop: "LIC-101" });
  });

  it("throws the server detail on a non-2xx reply", async () => {
    reply(404, { detail: "loop 'LIC-999' not found" });
    await expect(analyzeSteps("run1", { loop: "LIC-999" })).rejects.toThrow("loop 'LIC-999' not found");
  });

  it("throws an Error instance on a non-2xx reply", async () => {
    reply(422, { detail: "bad body" });
    await expect(analyzeSteps("run1", { loop: "LIC-101" })).rejects.toBeInstanceOf(Error);
  });

  it("falls back to the status text when the error body is not JSON", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response("boom", { status: 500, statusText: "Server Error" }))));
    await expect(analyzeSteps("run1", { loop: "LIC-101" })).rejects.toThrow("Server Error");
  });
});

// Keep the StepRow import used: the type is part of the module's public surface.
const verdictOfRow: StepRow["verdict"] = "ok";
void verdictOfRow;

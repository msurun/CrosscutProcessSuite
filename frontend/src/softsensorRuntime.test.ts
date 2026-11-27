// Unit tests of the pure helpers of the soft sensor Runtime panel and its API client.
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import {
  canApplyMode, eventsNewestFirst, modeErrorText, setSoftSensorMode, statusClass, statusMarker, valueText,
  type RuntimeEvent,
} from "./softsensorRuntime";

afterEach(() => vi.unstubAllGlobals());

describe("helpers", () => {
  it("marks every status with text as well as a class", () => {
    expect(statusMarker("good")).toBe("[OK]");
    expect(statusMarker("uncertain")).toBe("[?]");
    expect(statusMarker("bad")).toBe("[X]");
    expect(statusClass("bad")).toBe("status-chip--problem");
  });

  it("applies a mode only when it differs and nothing is running", () => {
    expect(canApplyMode("shadow", "backup", false)).toBe(true);
    expect(canApplyMode("shadow", "shadow", false)).toBe(false);
    expect(canApplyMode("shadow", "backup", true)).toBe(false);
  });

  it("formats missing values as dashes", () => {
    expect(valueText(null)).toBe("--");
    expect(valueText(NaN)).toBe("--");
    expect(valueText(1.23456, 2)).toBe("1.23");
  });

  it("sorts events newest first without changing the input", () => {
    const events: RuntimeEvent[] = [
      { t_utc: "2026-01-01T00:00:00Z", from: "instrument", to: "softsensor", reason: "a" },
      { t_utc: "2026-01-02T00:00:00Z", from: "softsensor", to: "instrument", reason: "b" },
    ];
    expect(eventsNewestFirst(events).map((e) => e.reason)).toEqual(["b", "a"]);
    expect(events[0].reason).toBe("a");
  });

  it("returns the exact error text", () => {
    expect(modeErrorText(new ApiError(409, "Refused text."))).toBe("Refused text.");
    expect(modeErrorText("boom")).toBe("boom");
  });
});

describe("client", () => {
  it("rejects a 409 with the exact detail", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ detail: "No." }), { status: 409 }))));
    await expect(setSoftSensorMode("s 1", "primary")).rejects.toMatchObject({ status: 409, message: "No." });
  });
});

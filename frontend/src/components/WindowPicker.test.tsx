// src/components/WindowPicker.test.tsx
//
// Behaviour tests for the free window picker: parsing, validation, the apply
// flow, taking the zoomed range, and resyncing the inputs when the window
// prop changes. The API and the trend pane are replaced with fakes.

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { LoopSummary, Series } from "../api";
import type { Translate } from "../findings";
import { makeLoop } from "../testFixtures";
import { isValidWindow, parseMinutes, WindowPicker } from "./WindowPicker";

/** Fake translator: echoes the key and the params, so a test can assert on either. */
const t: Translate = (key, params) => key + (params ? JSON.stringify(params) : "");

/** Seconds in a minute, for building expected second values. */
const SECONDS_PER_MINUTE = 60;

/** The zoom the TrendPane mock reports, in seconds since the first sample of the fixture. */
const ZOOM_MIN_S = 100;
const ZOOM_MAX_S = 400;

/** Epoch second of the first sample of the fixture (the plot axis is in epoch seconds). */
const FIRST_TIMESTAMP_S = 1_600_000_000;

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ...actual, fetchSeries: vi.fn() };
});

vi.mock("./TrendPane", () => ({
  // Exposes a button that performs the zoom the real pane would report to onZoom.
  TrendPane: (props: { labels: string[]; onZoom?: (min: number, max: number) => void }) => (
    <div role="img" aria-label={props.labels.join(", ")}>
      <button
        type="button"
        onClick={() => props.onZoom?.(FIRST_TIMESTAMP_S + ZOOM_MIN_S, FIRST_TIMESTAMP_S + ZOOM_MAX_S)}
      >
        zoom
      </button>
    </div>
  ),
}));

import { fetchSeries } from "../api";

/** The mocked loader, typed so each test can set its resolved or rejected value. */
const fetchSeriesMock = vi.mocked(fetchSeries);

/** One series in the API shape: timestamps in nanoseconds, values in the tag's unit. */
function makeSeries(tag: string): Series {
  const t: number[] = [];
  const mean: number[] = [];
  for (let second = 0; second <= 3600; second += 10) {
    t.push((FIRST_TIMESTAMP_S + second) * 1e9);
    mean.push(50);
  }
  return { tag, downsampled: false, t, min: [...mean], max: [...mean], mean };
}

/** A ready response for the default loop (PV and OUT). */
function readyResponse(loop: LoopSummary) {
  return { dataset_id: "ds1", series: [makeSeries(loop.pv), makeSeries(loop.out)] };
}

/** Render the picker with sane defaults; each test overrides only what it needs. */
function renderPicker(overrides: {
  window?: { startS: number; endS: number } | null;
  onSelectWindow?: (w: { startS: number; endS: number }) => void;
} = {}) {
  const loop = makeLoop();
  fetchSeriesMock.mockResolvedValue(readyResponse(loop));
  const onSelectWindow = overrides.onSelectWindow ?? vi.fn();
  render(
    <WindowPicker
      datasetId="ds1"
      loop={loop}
      window={overrides.window ?? null}
      onSelectWindow={onSelectWindow}
      t={t}
    />,
  );
  return { onSelectWindow };
}

afterEach(() => {
  cleanup();
  fetchSeriesMock.mockReset();
});

describe("parseMinutes", () => {
  it("parses a decimal point value", () => {
    expect(parseMinutes("1.5")).toBe(1.5);
  });

  it("parses a decimal comma value", () => {
    expect(parseMinutes("1,5")).toBe(1.5);
  });

  it("parses zero", () => {
    expect(parseMinutes("0")).toBe(0);
  });

  it("trims surrounding whitespace", () => {
    expect(parseMinutes("  2  ")).toBe(2);
  });

  it("returns null for empty text", () => {
    expect(parseMinutes("")).toBeNull();
  });

  it("returns null for letters", () => {
    expect(parseMinutes("abc")).toBeNull();
  });

  it("returns null for a negative value", () => {
    expect(parseMinutes("-1")).toBeNull();
  });

  it("returns null for a non-finite value", () => {
    expect(parseMinutes("Infinity")).toBeNull();
  });
});

describe("isValidWindow", () => {
  it("accepts a window inside the record", () => {
    expect(isValidWindow(10, 100, 200)).toBe(true);
  });

  it("accepts a window that fills the record", () => {
    expect(isValidWindow(0, 200, 200)).toBe(true);
  });

  it("accepts an end within rounding of the record length", () => {
    expect(isValidWindow(0, 200 + 1e-7, 200)).toBe(true);
  });

  it("rejects a negative start", () => {
    expect(isValidWindow(-1, 100, 200)).toBe(false);
  });

  it("rejects an empty window", () => {
    expect(isValidWindow(100, 100, 200)).toBe(false);
  });

  it("rejects an end past the record", () => {
    expect(isValidWindow(0, 300, 200)).toBe(false);
  });
});

describe("WindowPicker", () => {
  it("shows the loading text before the series arrive", () => {
    fetchSeriesMock.mockReturnValue(new Promise(() => {}));
    render(
      <WindowPicker
        datasetId="ds1"
        loop={makeLoop()}
        window={null}
        onSelectWindow={vi.fn()}
        t={t}
      />,
    );
    expect(screen.getByText("tuning.window.loadingTrend")).toBeTruthy();
  });

  it("shows both charts once the series arrive", async () => {
    renderPicker();
    expect(await screen.findByRole("img", { name: "tuning.window.pvLabel" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "tuning.window.outLabel" })).toBeTruthy();
  });

  it("shows the error text when loading fails", async () => {
    fetchSeriesMock.mockRejectedValue(new Error("boom"));
    render(
      <WindowPicker
        datasetId="ds1"
        loop={makeLoop()}
        window={null}
        onSelectWindow={vi.fn()}
        t={t}
      />,
    );
    expect(await screen.findByText(`trends.error${JSON.stringify({ reason: "Error: boom" })}`)).toBeTruthy();
  });

  it("applies typed minutes as seconds", async () => {
    const { onSelectWindow } = renderPicker();
    await screen.findByRole("img", { name: "tuning.window.pvLabel" });

    fireEvent.change(screen.getByLabelText("tuning.window.startMin"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("tuning.window.endMin"), { target: { value: "2" } });
    fireEvent.click(screen.getByText("tuning.window.apply"));

    expect(onSelectWindow).toHaveBeenCalledWith({
      startS: 1 * SECONDS_PER_MINUTE,
      endS: 2 * SECONDS_PER_MINUTE,
    });
  });

  it("disables apply and shows an alert for a window past the record", async () => {
    renderPicker();
    await screen.findByRole("img", { name: "tuning.window.pvLabel" });

    fireEvent.change(screen.getByLabelText("tuning.window.startMin"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("tuning.window.endMin"), { target: { value: "120" } });

    expect(screen.getByText("tuning.window.apply")).toHaveProperty("disabled", true);
    expect(screen.getByRole("alert").textContent).toBe("tuning.window.invalid");
  });

  it("takes the zoomed range relative to the first timestamp", async () => {
    const { onSelectWindow } = renderPicker();
    const pane = await screen.findByRole("img", { name: "tuning.window.pvLabel" });

    fireEvent.click(pane.querySelector("button")!);
    fireEvent.click(screen.getByText("tuning.window.useVisible"));

    // The pane reports epoch seconds; the window is in seconds since the first sample.
    expect(onSelectWindow).toHaveBeenCalledWith({ startS: ZOOM_MIN_S, endS: ZOOM_MAX_S });
  });

  it("resyncs the inputs when the window prop changes", async () => {
    const loop = makeLoop();
    fetchSeriesMock.mockResolvedValue(readyResponse(loop));
    const { rerender } = render(
      <WindowPicker datasetId="ds1" loop={loop} window={null} onSelectWindow={vi.fn()} t={t} />,
    );
    await screen.findByRole("img", { name: "tuning.window.pvLabel" });

    rerender(
      <WindowPicker
        datasetId="ds1"
        loop={loop}
        window={{ startS: 60, endS: 120 }}
        onSelectWindow={vi.fn()}
        t={t}
      />,
    );

    expect(screen.getByLabelText<HTMLInputElement>("tuning.window.startMin").value).toBe("1.0");
    expect(screen.getByLabelText<HTMLInputElement>("tuning.window.endMin").value).toBe("2.0");
  });
});

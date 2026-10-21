// src/components/TrendPane.test.tsx
// Tests of the pure range helper and of the TrendPane controls (range buttons, undo, legend, MODE note).
// uPlot is replaced by a recording fake because jsdom has no canvas.
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fittingPresets, modeSpans, presetRange } from "../trendData";
import { visibleRange } from "../visibleRange";

const fake = vi.hoisted(() => ({ instances: [] as Array<Record<string, any>>, deferScales: false }));

vi.mock("uplot", () => ({
  default: class {
    scales = { x: { min: undefined as number | undefined, max: undefined as number | undefined } };
    data: unknown;
    height = 100;
    opts: any;
    setScale = vi.fn((key: string, range: { min: number; max: number }) => {
      const apply = () => {
        this.scales.x = { min: range.min, max: range.max };
        this.opts.hooks.setScale[0](this, key);
      };
      // Real uPlot applies scales in a microtask, so right after construction x.min is still unset.
      if (fake.deferScales) queueMicrotask(apply);
      else apply();
    });
    setData = vi.fn();
    setSize = vi.fn();
    redraw = vi.fn();
    destroy = vi.fn();
    constructor(opts: any, data: unknown) {
      this.opts = opts;
      this.data = data;
      fake.instances.push(this as unknown as Record<string, any>);
    }
  },
}));
vi.mock("uplot/dist/uPlot.min.css", () => ({}));

import { TrendPane } from "./TrendPane";

const HOUR = 3600;
const TIMES = Array.from({ length: 31 }, (_, i) => i * HOUR); // 30 h of hourly samples
const T = (key: string) => key;

beforeEach(() => {
  fake.instances.length = 0;
  fake.deferScales = false;
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
});

function renderPane(extra: Record<string, unknown> = {}) {
  return render(
    <TrendPane data={[TIMES, TIMES.map((x) => x / 10)]} labels={["TIC1.PV"]} colors={["--series-1"]} t={T} roles={["pv"]} {...extra} />,
  );
}

describe("visibleRange", () => {
  it("returns the plot's own scale when both bounds are set", () => {
    expect(visibleRange(5, 15, [10, 20, 30])).toEqual([5, 15]);
  });

  it("falls back to the first and last time when the scale is not set", () => {
    expect(visibleRange(undefined, undefined, [10, 20, 30])).toEqual([10, 30]);
  });

  it("returns null when there is no data and no scale", () => {
    expect(visibleRange(undefined, undefined, [])).toBeNull();
  });

  it("returns null when a scale bound is not a finite number", () => {
    expect(visibleRange(NaN, 15, [10, 30])).toBeNull();
    expect(visibleRange(5, Infinity, [10, 30])).toBeNull();
  });

  it("returns null when a time stamp used as fallback is not a finite number", () => {
    expect(visibleRange(undefined, undefined, [NaN, 20])).toBeNull();
    expect(visibleRange(undefined, undefined, [10, null])).toBeNull();
  });
});

describe("range and MODE helpers", () => {
  it("offers only the presets shorter than the data", () => {
    expect(fittingPresets(TIMES)).toEqual(["1h", "8h", "24h", "all"]);
    expect(fittingPresets([0, 2 * HOUR])).toEqual(["1h", "all"]);
    expect(fittingPresets([])).toEqual(["all"]);
  });

  it("computes the last-N-hours range, clamped to the data", () => {
    expect(presetRange(TIMES, "8h")).toEqual([22 * HOUR, 30 * HOUR]);
    expect(presetRange(TIMES, "all")).toEqual([0, 30 * HOUR]);
    expect(presetRange([], "1h")).toBeNull();
  });

  it("finds the stretches where the controller is in manual (0)", () => {
    expect(modeSpans([0, 1, 2, 3, 4, 5], [1, 1, 0, 0, 1, 1])).toEqual([[2, 4]]);
    expect(modeSpans([0, 1, 2, 3], [1, 1, 1, 0])).toEqual([[3, 3]]);
    expect(modeSpans([0, 1, 2], [2, 2, 2])).toEqual([]);
    expect(modeSpans([0, 1], [null, null])).toEqual([]);
  });
});

describe("TrendPane controls", () => {
  it("shows only the range buttons that fit the data", () => {
    renderPane();
    expect(screen.getByRole("button", { name: "trends.range.24h" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "trends.range.all" })).toBeInTheDocument();
  });

  it("applies a preset and Undo restores the previous range", () => {
    renderPane();
    const plot = fake.instances[0];
    plot.setScale("x", { min: 0, max: 30 * HOUR });
    const undo = screen.getByRole("button", { name: "trends.undoZoom" });
    expect(undo).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "trends.range.1h" }));
    expect(plot.scales.x).toEqual({ min: 29 * HOUR, max: 30 * HOUR });
    expect(undo).toBeEnabled();
    fireEvent.click(undo);
    expect(plot.scales.x).toEqual({ min: 0, max: 30 * HOUR });
    expect(undo).toBeDisabled();
  });

  it("puts the role in the legend and shows the last value when not hovering", () => {
    renderPane();
    const series = fake.instances[0].opts.series[1];
    expect(series.label).toBe("trend.role.pv TIC1.PV");
    const self = { data: [TIMES, TIMES.map((x) => x / 10)] };
    expect(series.value(self, null, 1, null)).toBe("10800.00");
    expect(series.value(self, 5, 1, 7)).toBe("5.00");
  });

  it("explains the MODE band only when a stretch is shaded", () => {
    renderPane({ mode: TIMES.map((_, i) => (i > 20 ? 0 : 1)) });
    expect(screen.getByText("trend.modeBand")).toBeInTheDocument();
  });

  it("shows no MODE note without a mode tag", () => {
    renderPane();
    expect(screen.queryByText("trend.modeBand")).not.toBeInTheDocument();
  });
});

describe("TrendPane first paint", () => {
  it("does not call redraw() before uPlot has committed its x scale (that left the plot without lines)", async () => {
    fake.deferScales = true;
    renderPane({ mode: TIMES.map(() => 1) });

    const plot = fake.instances[0];
    expect(plot.redraw).not.toHaveBeenCalled();
    await Promise.resolve();
    expect(plot.scales.x.min).toBe(TIMES[0]);
  });

  it("redraws the MODE band when the mode data changes on a plot that has its scale", () => {
    const { rerender } = renderPane({ mode: TIMES.map(() => 1) });
    const plot = fake.instances[0];
    plot.redraw.mockClear();

    rerender(<TrendPane data={[TIMES, TIMES.map((x) => x / 10)]} labels={["TIC1.PV"]} colors={["--series-1"]} t={T} roles={["pv"]} mode={TIMES.map(() => 0)} />);

    expect(plot.redraw).toHaveBeenCalledTimes(1);
  });
});

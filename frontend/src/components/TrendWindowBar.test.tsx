// frontend/src/components/TrendWindowBar.test.tsx
// Tests for TrendWindowBar: presets, panning, live toggle, mode switching and invalid absolute ranges.
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TrendWindow } from "../trendWindow";
import { TrendWindowBar } from "./TrendWindowBar";

const t = (key: string, vars?: Record<string, string | number>) => (vars ? `${key} ${JSON.stringify(vars)}` : key);
const NOW_MS = Date.parse("2026-01-02T12:00:00Z");

function setup(window: TrendWindow) {
  const onChange = vi.fn();
  render(<TrendWindowBar t={t} window={window} nowMs={NOW_MS} onChange={onChange} />);
  return onChange;
}

describe("TrendWindowBar", () => {
  it("a preset sets last_s", () => {
    const onChange = setup({ kind: "relative", last_s: 3600 });
    fireEvent.click(screen.getByRole("button", { name: "8h" }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ kind: "relative", last_s: 28800 }));
  });

  it("marks the active preset as pressed", () => {
    setup({ kind: "relative", last_s: 3600 });
    expect(screen.getByRole("button", { name: "1h" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "8h" })).toHaveAttribute("aria-pressed", "false");
  });

  it("back and forward shift an absolute window by its width", () => {
    const w: TrendWindow = { kind: "absolute", start_utc: "2026-01-02T10:00:00.000Z", end_utc: "2026-01-02T11:00:00.000Z" };
    const onChange = setup(w);
    fireEvent.click(screen.getByRole("button", { name: "trendWindow.back" }));
    expect(onChange).toHaveBeenLastCalledWith({ kind: "absolute", start_utc: "2026-01-02T09:00:00.000Z", end_utc: "2026-01-02T10:00:00.000Z" });
    fireEvent.click(screen.getByRole("button", { name: "trendWindow.forward" }));
    expect(onChange).toHaveBeenLastCalledWith({ kind: "absolute", start_utc: "2026-01-02T11:00:00.000Z", end_utc: "2026-01-02T12:00:00.000Z" });
  });

  it("toggles live and keeps a refresh period", () => {
    const onChange = setup({ kind: "relative", last_s: 3600 });
    fireEvent.click(screen.getByRole("checkbox", { name: "trendWindow.live" }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ live: true, refresh_s: 10 }));
  });

  it("switches to absolute using the resolved range", () => {
    const onChange = setup({ kind: "relative", last_s: 3600 });
    fireEvent.click(screen.getByRole("button", { name: "trendWindow.mode.absolute" }));
    expect(onChange).toHaveBeenCalledWith({ kind: "absolute", start_utc: "2026-01-02T11:00:00.000Z", end_utc: "2026-01-02T12:00:00.000Z" });
  });

  it("switches back to relative keeping the width as last_s", () => {
    const onChange = setup({ kind: "absolute", start_utc: "2026-01-02T10:00:00.000Z", end_utc: "2026-01-02T12:00:00.000Z" });
    fireEvent.click(screen.getByRole("button", { name: "trendWindow.mode.relative" }));
    expect(onChange).toHaveBeenCalledWith({ kind: "relative", last_s: 7200 });
  });

  it("applies a custom width in hours", () => {
    const onChange = setup({ kind: "relative", last_s: 3600 });
    fireEvent.change(screen.getByLabelText("trendWindow.customAmount"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "trendWindow.apply" }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ last_s: 7200 }));
  });

  it("shows the problem for an absolute range that ends before it starts", () => {
    setup({ kind: "absolute", start_utc: "2026-01-02T12:00:00.000Z", end_utc: "2026-01-02T10:00:00.000Z" });
    expect(screen.getByRole("status")).toHaveTextContent("trendWindow.problem.end_before_start");
  });
});

// Component tests of the global status bar (#174): loading, unavailable, populated and the queue click.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LOADING_DATA, type StatusBarData } from "../statusBarModel";
import { StatusBar } from "./StatusBar";

const t = (key: string, params?: Record<string, string | number>) => (params ? `${key}:${params.count}` : key);

const POPULATED: StatusBarData = {
  gateway: { state: "ready", value: { mode: "supervised", targets: {}, pending: 4 } },
  runtime: { state: "ready", value: { service: { running: false, updated_at_utc: null }, jobs: [] } },
  loops: { state: "ready", value: [] },
  equipment: { state: "ready", value: [] },
};

afterEach(cleanup);

describe("StatusBar", () => {
  it("shows a loading placeholder in every item", () => {
    render(<StatusBar data={LOADING_DATA} onOpenQueue={() => {}} t={t} />);
    expect(screen.getAllByText("statusBar.loading")).toHaveLength(5);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows unavailable per failed source and keeps the rest", () => {
    render(<StatusBar data={{ ...POPULATED, gateway: { state: "unavailable" } }} onOpenQueue={() => {}} t={t} />);
    expect(screen.getAllByText("statusBar.unavailable")).toHaveLength(3);
    expect(screen.getByText("statusBar.runtime.stopped")).toBeTruthy();
  });

  it("shows the populated values", () => {
    render(<StatusBar data={POPULATED} onOpenQueue={() => {}} t={t} />);
    expect(screen.getByText("gateway.mode.supervised")).toBeTruthy();
    expect(screen.getByText("statusBar.kill.clear")).toBeTruthy();
    expect(screen.getByText("statusBar.alarms.count:0")).toBeTruthy();
  });

  it("opens the approval queue when the waiting count is clicked", () => {
    const open = vi.fn();
    render(<StatusBar data={POPULATED} onOpenQueue={open} t={t} />);
    fireEvent.click(screen.getByRole("button"));
    expect(open).toHaveBeenCalledTimes(1);
  });
});

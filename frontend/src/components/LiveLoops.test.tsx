// Tests of the live loops worklist: rows, badges, finding text, detail panel and the 30 s refresh.
// A fake translator returns keys plus params, so assertions compare keys.
import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { LiveLoop } from "../liveLoopsApi";
import { LiveLoops, REFRESH_MS, liveFindingText, relativeTime, useLiveLoops } from "./LiveLoops";

vi.mock("./TrendPane", () => ({ TrendPane: () => <div data-testid="trend" /> }));

const t = (key: string, params?: Record<string, string | number>) => key + (params ? JSON.stringify(params) : "");

function loop(over: Partial<LiveLoop>): LiveLoop {
  return { id: "l1", name: "L1", type: "flow", job: "j1", job_status: "idle", last_run_utc: null, fresh: true, kpi: null, findings: [], ...over };
}

function stubFetch(loops: LiveLoop[]) {
  const mock = vi.fn(async (url: string) => {
    const body = url.includes("?limit") ? { ...loops[0], history: [1, 2].map((i) => ({ utc: `2026-01-01T00:0${i}:00Z`, kpi: { harris_index: 0.5 } })) } : { loops };
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("LiveLoops", () => {
  it("shows the no-job hint, the stale badge and findings with since", () => {
    const loops = [
      loop({ id: "a", name: "A", job: null, job_status: null }),
      loop({ id: "b", name: "B", fresh: false, last_run_utc: "2026-01-01T00:00:00Z", kpi: { saturation_fraction: 0.31 }, findings: [{ code: "saturated", since_utc: "2026-01-01T00:00:00Z" }] }),
    ];
    render(<LiveLoops loops={loops} t={t} />);
    expect(screen.getByText("liveLoops.noJobHint")).toBeTruthy();
    expect(screen.getByText("liveLoops.stale")).toBeTruthy();
    expect(screen.getByText(/finding.saturated\{"percent":31\}/)).toBeTruthy();
    expect(screen.getByText(/liveLoops.since/)).toBeTruthy();
  });

  it("opens the detail panel with the history chart on selection", async () => {
    stubFetch([loop({ kpi: { harris_index: 0.5, classification: "ok" } })]);
    render(<LiveLoops loops={[loop({ kpi: { harris_index: 0.5, classification: "ok" } })]} t={t} />);
    fireEvent.click(screen.getByRole("button", { name: "L1" }));
    expect(screen.getByRole("region")).toBeTruthy();
    await waitFor(() => expect(screen.getByTestId("trend")).toBeTruthy());
    expect(screen.getByText("liveLoops.pastWindowHint")).toBeTruthy();
  });

  it("takes oscillation minutes and manual percent from the KPI", () => {
    expect(liveFindingText(t, "oscillating", { oscillation_period_s: 90 })).toBe('finding.oscillating{"minutes":1.5}');
    expect(liveFindingText(t, "manual", { service_factor: 0.8 })).toBe('finding.manual{"percent":20}');
  });

  it("formats relative time and tolerates missing times", () => {
    expect(relativeTime(null)).toBe("");
    expect(relativeTime("2026-01-01T00:00:00Z", Date.parse("2026-01-01T00:05:00Z"))).toContain("5");
  });

  it("refetches the list every 30 seconds", async () => {
    vi.useFakeTimers();
    const mock = stubFetch([loop({})]);
    const { result } = renderHook(() => useLiveLoops());
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(result.current.loops).toHaveLength(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(REFRESH_MS); });
    expect(mock).toHaveBeenCalledTimes(2);
  });
});

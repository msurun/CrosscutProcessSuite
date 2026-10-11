import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LoopsOverview, countByStatus } from "./LoopsOverview";
import type { LoopSummary } from "../api";

// ---------------------------------------------------------------------------
// Fixtures and helpers
// ---------------------------------------------------------------------------

/**
 * Builds a fully populated LoopSummary so each test only states the fields it
 * cares about. Defaults describe a healthy loop.
 */
function makeLoop(overrides: Partial<LoopSummary> = {}): LoopSummary {
  return {
    name: "Loop A",
    pv: "PV",
    sp: "SP",
    out: "OUT",
    mode: "AUTO",
    unit: "degC",
    status: "ok",
    health_percent: 80,
    classification: "good",
    findings: [],
    service_percent: 100,
    saturation_percent: 0,
    harris_index: 0.7,
    oscillation_period_s: null,
    stiction_verdict: "no_stiction",
    sparkline: [1, 2, 3, 2],
    ...overrides,
  };
}

/**
 * Fake translator: returns the key plus stringified params so a test can assert
 * an exact string such as `finding.saturated{"percent":31}`.
 */
const t = (key: string, params?: Record<string, string | number>) =>
  key + (params ? JSON.stringify(params) : "");

/**
 * Returns the loop names in the order they appear in the rendered table.
 */
function renderedLoopNames(): string[] {
  const table = screen.getByRole("table");
  const bodyRows = within(table).getAllByRole("row").slice(1); // skip header row
  return bodyRows.map((row) => within(row).getAllByRole("cell")[1].textContent ?? "");
}

// ---------------------------------------------------------------------------
// Row order
// ---------------------------------------------------------------------------

describe("LoopsOverview row order", () => {
  it("sorts rows by status problem, warning, ok, unused before anything else", () => {
    render(
      <LoopsOverview
        loops={[
          makeLoop({ name: "unused loop", status: "unused" }),
          makeLoop({ name: "ok loop", status: "ok" }),
          makeLoop({ name: "warning loop", status: "warning" }),
          makeLoop({ name: "problem loop", status: "problem" }),
        ]}
        t={t}
        onOpen={vi.fn()}
      />,
    );

    expect(renderedLoopNames()).toEqual([
      "problem loop",
      "warning loop",
      "ok loop",
      "unused loop",
    ]);
  });

  it("sorts loops with the same status by health ascending", () => {
    render(
      <LoopsOverview
        loops={[
          makeLoop({ name: "healthy", status: "ok", health_percent: 95 }),
          makeLoop({ name: "sick", status: "ok", health_percent: 40 }),
          makeLoop({ name: "middling", status: "ok", health_percent: 70 }),
        ]}
        t={t}
        onOpen={vi.fn()}
      />,
    );

    expect(renderedLoopNames()).toEqual(["sick", "middling", "healthy"]);
  });
});

// ---------------------------------------------------------------------------
// Opening a loop
// ---------------------------------------------------------------------------

describe("LoopsOverview opening a loop", () => {
  it("calls onOpen with the loop name when the name button is clicked", () => {
    const onOpen = vi.fn();
    render(<LoopsOverview loops={[makeLoop({ name: "Reactor TIC-101" })]} t={t} onOpen={onOpen} />);

    fireEvent.click(screen.getByRole("button", { name: "Reactor TIC-101" }));

    expect(onOpen).toHaveBeenCalledWith("Reactor TIC-101");
  });
});

// ---------------------------------------------------------------------------
// Summary text
// ---------------------------------------------------------------------------

describe("LoopsOverview summary text", () => {
  it("counts problem and warning loops in the attention summary", () => {
    render(
      <LoopsOverview
        loops={[
          makeLoop({ name: "a", status: "problem" }),
          makeLoop({ name: "b", status: "warning" }),
          makeLoop({ name: "c", status: "warning" }),
          makeLoop({ name: "d", status: "ok" }),
          makeLoop({ name: "e", status: "unused" }),
        ]}
        t={t}
        onOpen={vi.fn()}
      />,
    );

    expect(screen.getByText('loops.attention{"count":3}')).toBeInTheDocument();
  });

  it("shows a zero attention count when every loop is fine", () => {
    render(<LoopsOverview loops={[makeLoop({ status: "ok" })]} t={t} onOpen={vi.fn()} />);

    expect(screen.getByText('loops.attention{"count":0}')).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Filtering
// ---------------------------------------------------------------------------

describe("LoopsOverview filtering", () => {
  it("marks the all filter as pressed by default", () => {
    render(<LoopsOverview loops={[makeLoop({ status: "ok" })]} t={t} onOpen={vi.fn()} />);

    expect(screen.getByRole("button", { name: "loops.filter.all" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("labels a status filter with its status text and occurring count", () => {
    render(
      <LoopsOverview
        loops={[
          makeLoop({ name: "a", status: "warning" }),
          makeLoop({ name: "b", status: "warning" }),
          makeLoop({ name: "c", status: "ok" }),
        ]}
        t={t}
        onOpen={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "status.warning (2)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "status.ok (1)" })).toBeInTheDocument();
  });

  it("hides the rows of statuses that are not selected", () => {
    render(
      <LoopsOverview
        loops={[
          makeLoop({ name: "warning loop", status: "warning" }),
          makeLoop({ name: "ok loop", status: "ok" }),
        ]}
        t={t}
        onOpen={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "status.warning (1)" }));

    expect(renderedLoopNames()).toEqual(["warning loop"]);
  });

  it("shows every row again after the all filter is clicked back", () => {
    render(
      <LoopsOverview
        loops={[
          makeLoop({ name: "warning loop", status: "warning" }),
          makeLoop({ name: "ok loop", status: "ok" }),
        ]}
        t={t}
        onOpen={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "status.warning (1)" }));
    fireEvent.click(screen.getByRole("button", { name: "loops.filter.all" }));

    expect(renderedLoopNames()).toEqual(["warning loop", "ok loop"]);
  });
});

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

describe("LoopsOverview empty state", () => {
  it("shows the none message and no table when there are no loops", () => {
    render(<LoopsOverview loops={[]} t={t} onOpen={vi.fn()} />);

    expect(screen.getByText("loops.none")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Cell contents
// ---------------------------------------------------------------------------

describe("LoopsOverview cell contents", () => {
  it("shows a dash in the health cell when health_percent is null", () => {
    render(
      <LoopsOverview loops={[makeLoop({ name: "no health", health_percent: null })]} t={t} onOpen={vi.fn()} />,
    );

    const row = screen.getByRole("row", { name: /no health/ });
    expect(within(row).getByText("–")).toBeInTheDocument();
  });

  it("shows the first finding translated with its params", () => {
    render(
      <LoopsOverview
        loops={[
          makeLoop({
            name: "saturated loop",
            findings: [
              { code: "saturated", params: { percent: 31 } },
              { code: "oscillating", params: { period_s: 120 } },
            ],
          }),
        ]}
        t={t}
        onOpen={vi.fn()}
      />,
    );

    expect(screen.getByText('finding.saturated{"percent":31}')).toBeInTheDocument();
  });

  it("shows the no-findings message when the loop has no findings", () => {
    render(<LoopsOverview loops={[makeLoop({ name: "quiet", findings: [] })]} t={t} onOpen={vi.fn()} />);

    expect(screen.getByText("loops.noFindings")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// countByStatus helper
// ---------------------------------------------------------------------------

describe("countByStatus", () => {
  it("counts the loops for each occurring status", () => {
    const counts = countByStatus([
      makeLoop({ name: "a", status: "problem" }),
      makeLoop({ name: "b", status: "warning" }),
      makeLoop({ name: "c", status: "warning" }),
      makeLoop({ name: "d", status: "ok" }),
    ]);

    expect(counts).toEqual({ problem: 1, warning: 2, ok: 1 });
  });

  it("returns an empty record for an empty list", () => {
    expect(countByStatus([])).toEqual({});
  });
});

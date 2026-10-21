// Unit tests for the LoopsOverview worklist table: default order, sorting, status filters,
// search, the attention count, the empty state, badges, links and cell text.
// A fake translator is used, so assertions compare translation keys and their parameters.
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LoopsOverview, countByStatus } from "./LoopsOverview";
import { makeLoop } from "../testFixtures";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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
  return bodyRows.map((row) => within(row).getByRole("rowheader").textContent ?? "");
}

// ---------------------------------------------------------------------------
// Row order and sorting
// ---------------------------------------------------------------------------

describe("LoopsOverview row order", () => {
  it("lists rows by priority_rank by default, not by name", () => {
    render(
      <LoopsOverview
        loops={[
          makeLoop({ name: "alpha", priority_rank: 3 }),
          makeLoop({ name: "bravo", priority_rank: 1 }),
          makeLoop({ name: "charlie", priority_rank: 2 }),
        ]}
        t={t}
        onOpen={vi.fn()}
      />,
    );

    expect(renderedLoopNames()).toEqual(["bravo", "charlie", "alpha"]);
  });

  it("sorts by status problem, warning, ok, unused when the status header is clicked", () => {
    render(
      <LoopsOverview
        loops={[
          makeLoop({ name: "unused loop", status: "unused", priority_rank: 1 }),
          makeLoop({ name: "ok loop", status: "ok", priority_rank: 2 }),
          makeLoop({ name: "warning loop", status: "warning", priority_rank: 3 }),
          makeLoop({ name: "problem loop", status: "problem", priority_rank: 4 }),
        ]}
        t={t}
        onOpen={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "loops.column.status" }));

    expect(renderedLoopNames()).toEqual(["problem loop", "warning loop", "ok loop", "unused loop"]);
  });

  it("sorts by health ascending when the health header is clicked", () => {
    render(
      <LoopsOverview
        loops={[
          makeLoop({ name: "healthy", health_percent: 95, priority_rank: 1 }),
          makeLoop({ name: "sick", health_percent: 40, priority_rank: 2 }),
          makeLoop({ name: "middling", health_percent: 70, priority_rank: 3 }),
        ]}
        t={t}
        onOpen={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "loops.column.health" }));

    expect(renderedLoopNames()).toEqual(["sick", "middling", "healthy"]);
  });

  it("sets aria-sort on the clicked column and reverses the order on a second click", () => {
    render(
      <LoopsOverview
        loops={[
          makeLoop({ name: "beta", priority_rank: 1 }),
          makeLoop({ name: "alpha", priority_rank: 2 }),
          makeLoop({ name: "gamma", priority_rank: 3 }),
        ]}
        t={t}
        onOpen={vi.fn()}
      />,
    );
    const header = screen.getByRole("columnheader", { name: "loops.column.loop" });

    fireEvent.click(within(header).getByRole("button"));
    expect(header).toHaveAttribute("aria-sort", "ascending");
    expect(renderedLoopNames()).toEqual(["alpha", "beta", "gamma"]);

    fireEvent.click(within(header).getByRole("button"));
    expect(header).toHaveAttribute("aria-sort", "descending");
    expect(renderedLoopNames()).toEqual(["gamma", "beta", "alpha"]);
  });
});

// ---------------------------------------------------------------------------
// Opening a loop
// ---------------------------------------------------------------------------

describe("LoopsOverview opening a loop", () => {
  it("calls onOpen with the loop name when the name button is clicked", () => {
    const onOpen = vi.fn();
    render(<LoopsOverview loops={[makeLoop({ name: "Reactor TIC-101" })]} t={t} onOpen={onOpen} />);

    fireEvent.click(screen.getByRole("button", { name: 'loops.openLoop{"name":"Reactor TIC-101"}' }));

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

    expect(screen.getByRole("button", { name: "loops.filter.all (1)" })).toHaveAttribute(
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
          makeLoop({ name: "warning loop", status: "warning", priority_rank: 1 }),
          makeLoop({ name: "ok loop", status: "ok", priority_rank: 2 }),
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
          makeLoop({ name: "warning loop", status: "warning", priority_rank: 1 }),
          makeLoop({ name: "ok loop", status: "ok", priority_rank: 2 }),
        ]}
        t={t}
        onOpen={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "status.warning (1)" }));
    fireEvent.click(screen.getByRole("button", { name: "loops.filter.all (2)" }));

    expect(renderedLoopNames()).toEqual(["warning loop", "ok loop"]);
  });
});

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

describe("LoopsOverview search", () => {
  it("narrows the rows to the loops matching the search text", () => {
    render(
      <LoopsOverview
        loops={[
          makeLoop({ name: "Reactor TIC-101", priority_rank: 1 }),
          makeLoop({ name: "Mixer FIC-200", priority_rank: 2 }),
        ]}
        t={t}
        onOpen={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByRole("searchbox", { name: "loops.search" }), { target: { value: "mixer" } });

    expect(renderedLoopNames()).toEqual(["Mixer FIC-200"]);
  });

  it("shows the no-match state, and the clear button restores every row", () => {
    render(
      <LoopsOverview
        loops={[makeLoop({ name: "Reactor TIC-101" })]}
        t={t}
        onOpen={vi.fn()}
      />,
    );
    const search = screen.getByRole("searchbox", { name: "loops.search" });

    fireEvent.change(search, { target: { value: "no such loop" } });
    expect(screen.getByText("loops.noMatch")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "loops.clearFilters" }));
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(search).toHaveValue("");
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
// Toolbar and badges
// ---------------------------------------------------------------------------

describe("LoopsOverview toolbar", () => {
  it("shows the CSV export button", () => {
    render(<LoopsOverview loops={[makeLoop()]} t={t} onOpen={vi.fn()} />);

    expect(screen.getByRole("button", { name: "loops.exportCsv" })).toBeInTheDocument();
  });
});

describe("LoopsOverview partial assessment badge", () => {
  it("marks only the loops that have withheld conclusions", () => {
    render(
      <LoopsOverview
        loops={[
          makeLoop({ name: "partly known", not_assessed: ["harris"], priority_rank: 1 }),
          makeLoop({ name: "fully known", not_assessed: [], priority_rank: 2 }),
        ]}
        t={t}
        onOpen={vi.fn()}
      />,
    );

    const partial = screen.getByRole("row", { name: /partly known/ });
    expect(within(partial).getByText("loops.partial")).toHaveAttribute(
      "title",
      'loops.partialHint{"missing":"withheld.harris"}',
    );
    const full = screen.getByRole("row", { name: /fully known/ });
    expect(within(full).queryByText("loops.partial")).not.toBeInTheDocument();
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

  it("shows 'no conclusion' instead of 'no problems' for a not_assessed loop", () => {
    render(<LoopsOverview loops={[makeLoop({ name: "unknown", status: "not_assessed", findings: [], not_assessed: ["harris"] })]} t={t} onOpen={vi.fn()} />);

    expect(screen.getByText("loops.noConclusion")).toBeInTheDocument();
    expect(screen.queryByText("loops.noFindings")).not.toBeInTheDocument();
  });

  it("shows the next action as its translated key with params", () => {
    render(
      <LoopsOverview
        loops={[
          makeLoop({
            name: "valve loop",
            next_action: { code: "valve_test", params: { percent: 12 } },
          }),
        ]}
        t={t}
        onOpen={vi.fn()}
      />,
    );

    expect(screen.getByText('action.valve_test{"percent":12}')).toBeInTheDocument();
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

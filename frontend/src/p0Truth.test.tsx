// Pins the UI behaviour that the "truth fixes" corrected: unknown health, partial assessment,
// and fuzzy axis ticks. One topic per describe block; the fake translator returns keys.
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LoopsOverview } from "./components/LoopsOverview";
import { LoopDetail } from "./components/LoopDetail";
import { MembershipChart } from "./components/MembershipChart";
import { applyQuery, type OverviewQuery } from "./worklist";
import { makeLoop } from "./testFixtures";
import type { LoopStatus } from "./api";
import type { FuzzyVariable } from "./fuzzy";

vi.mock("./api", () => ({
  fetchSeries: vi.fn().mockResolvedValue({ dataset_id: "d", series: [] }),
}));

// The loop-data editor has its own tests and would call the network here.
vi.mock("./components/KnowledgeEditor", () => ({ KnowledgeEditor: () => null }));

vi.mock("./components/TrendPane", () => ({
  TrendPane: ({ labels }: { labels: string[] }) => <div role="img" aria-label={labels.join(", ")} />,
}));

/** Fake translator: returns the key plus stringified params, as in the other test files. */
const t = (key: string, params?: Record<string, string | number>) =>
  key + (params ? JSON.stringify(params) : "");

afterEach(() => {
  cleanup();
});

/** Renders the worklist with the given loops and a no-op open handler. */
function renderOverview(loops: ReturnType<typeof makeLoop>[]) {
  render(<LoopsOverview loops={loops} t={t} onOpen={vi.fn()} />);
}

/** Renders the loop detail with no-op handlers for the loop and its tuning/benefit links. */
function renderDetail(loop: ReturnType<typeof makeLoop>) {
  render(
    <LoopDetail
      datasetId="d"
      loop={loop}
      t={t}
      onBack={vi.fn()}
      onOpenTuning={vi.fn()}
      onOpenBenefit={vi.fn()}
    />,
  );
}

describe("LoopsOverview not_assessed status", () => {
  it("labels the status chip and shows a filter button carrying the count", () => {
    renderOverview([makeLoop({ status: "not_assessed" })]);

    const table = screen.getByRole("table");
    expect(within(table).getByText("status.not_assessed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "status.not_assessed (1)" })).toBeInTheDocument();
  });
});

describe("LoopsOverview unknown health", () => {
  it("shows an en dash, no progress bar and the not-scored hint", () => {
    renderOverview([makeLoop({ health_percent: null })]);

    const cell = screen.getByText("–").closest("td");
    expect(cell).not.toBeNull();
    expect(cell?.querySelector("progress")).toBeNull();
    expect(cell).toHaveAttribute("title", "health.notScoredHint");
  });
});

describe("worklist status sort", () => {
  it("orders problem, warning, not_assessed, ok, unused from top to bottom", () => {
    const statuses: LoopStatus[] = ["unused", "ok", "not_assessed", "warning", "problem"];
    const loops = statuses.map((status, index) =>
      makeLoop({ name: `Loop ${index}`, status, priority_rank: index + 1 }),
    );
    const query: OverviewQuery = { status: "all", search: "", sortKey: "status", sortDirection: "asc" };

    const ordered = applyQuery(loops, query);

    expect(ordered.map((loop) => loop.status)).toEqual([
      "problem",
      "warning",
      "not_assessed",
      "ok",
      "unused",
    ]);
  });
});

describe("LoopDetail partial assessment", () => {
  it("says no findings covers only the checks that ran and lists what is missing", () => {
    renderDetail(makeLoop({ findings: [], not_assessed: ["harris", "oscillation_amplitude"] }));

    expect(screen.getByText(/^loops\.noFindingsPartial/)).toBeInTheDocument();
    expect(screen.queryByText("loops.noFindings")).not.toBeInTheDocument();
    expect(screen.getByText(/^next\.partial/)).toBeInTheDocument();
    expect(screen.queryByText(/^next\.ok/)).not.toBeInTheDocument();
  });
});

describe("LoopDetail full assessment", () => {
  it("says there are no findings and no action is needed", () => {
    renderDetail(makeLoop({ findings: [], not_assessed: [] }));

    expect(screen.getByText("loops.noFindings")).toBeInTheDocument();
    expect(screen.getByText(/^next\.ok/)).toBeInTheDocument();
  });
});

describe("LoopDetail header health", () => {
  it("marks an unknown health as not scored", () => {
    renderDetail(makeLoop({ health_percent: null }));

    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("health.notScored");
  });

  it("shows the percent when health is known", () => {
    renderDetail(makeLoop({ health_percent: 70 }));

    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent('health.label{"percent":70}');
  });
});

describe("MembershipChart axis ticks", () => {
  it("prints the full range values, not their leading digits", () => {
    const variable: FuzzyVariable = {
      id: "mill_power",
      label: "Mill power",
      unit: "kW",
      low: 2600,
      high: 3400,
      terms: [{ name: "normal", shape: "tri", params: [2800, 3000, 3200] }],
    };

    const { container } = render(<MembershipChart variable={variable} />);

    const ticks = Array.from(container.querySelectorAll(".chart-ticks span")).map((span) => span.textContent);
    expect(ticks).toEqual(["2600", "3000", "3400"]);
  });
});

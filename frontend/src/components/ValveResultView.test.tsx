// src/components/ValveResultView.test.tsx
// Behaviour tests for ValveResultView: verdict, key numbers, moves and callbacks.
// The charts are replaced by a stub; they are covered by the TrendPane tests.

import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ValveAnalysis, ValveResult } from "../api";
import { makeLoop } from "../testFixtures";
import { ValveResultView } from "./ValveResultView";

vi.mock("./TrendPane", () => ({
  TrendPane: ({ labels }: { labels: string[] }) => <div data-testid="trend-pane">{labels[0]}</div>,
}));

/** Fake translator: the key plus stringified params. */
const t = (key: string, params?: Record<string, string | number>) =>
  key + (params ? JSON.stringify(params) : "");

/** A complete result with a measurable deadband; overrides make the other cases. */
function makeResult(overrides: Partial<ValveResult> = {}): ValveResult {
  return {
    deadband: 0.5,
    deadband_bracket: [0.25, 1],
    deadband_lower_bound: null,
    resolution_le: 0.25,
    gain: 1.2,
    sigma_pv: 0.03,
    pv_left_band: false,
    reason_code: "",
    reason: "",
    moves: [
      { start_index: 10, op_change: 1, pv_change: 0, moved: false, size: 1, after_reversal: true },
      { start_index: 40, op_change: -1, pv_change: 1.2, moved: true, size: 1, after_reversal: false },
      { start_index: 70, op_change: 0.25, pv_change: null, moved: false, size: 0.25, after_reversal: false },
    ],
    ...overrides,
  };
}

/** Wraps a result into an analysis with a tiny record. */
function makeAnalysis(result: ValveResult): ValveAnalysis {
  return {
    result,
    record: {
      n_samples: 3,
      start_s: 0,
      end_s: 2,
      series: { t_s: [0, 1, 2], op: [50, 51, 51], pv: [10, 10, 11] },
    },
  };
}

/** Renders the view for a result and returns the spies. */
function setup(result: ValveResult) {
  const onAgain = vi.fn();
  const onNewPlan = vi.fn();
  render(
    <ValveResultView
      analysis={makeAnalysis(result)}
      loop={makeLoop({ unit: "bar" })}
      onAgain={onAgain}
      onNewPlan={onNewPlan}
      t={t}
    />,
  );
  return { onAgain, onNewPlan };
}

/** Text of the definition that follows the given term. */
function valueOf(term: string): string {
  return screen.getByText(term).nextElementSibling?.textContent ?? "";
}

describe("ValveResultView (complete result)", () => {
  it("states the deadband in the verdict", () => {
    setup(makeResult());

    expect(screen.getByRole("status")).toHaveTextContent('valve.result.summaryDeadband{"value":"0.5"}');
  });

  it("says the valve is good when the deadband is below 0.1", () => {
    setup(makeResult({ deadband: 0.05 }));

    expect(screen.getByRole("status")).toHaveTextContent("valve.result.summaryGood");
  });

  it("shows deadband bracket, resolution, gain with unit and noise", () => {
    setup(makeResult());

    expect(valueOf("valve.result.deadband")).toBe(
      'valve.result.deadbandValue{"value":"0.5","low":"0.25","high":"1"}',
    );
    expect(valueOf("valve.result.resolution")).toBe('valve.result.resolutionValue{"value":"0.25"}');
    expect(valueOf("valve.result.gain")).toBe('valve.result.gainValue{"value":"1.2","unit":"bar"}');
    expect(valueOf("valve.result.noise")).toBe("0.03 bar");
  });

  it("renders the OP and PV charts", () => {
    setup(makeResult());

    const panes = screen.getAllByTestId("trend-pane");
    expect(panes.map((pane) => pane.textContent)).toEqual(["valve.result.chartOp", "valve.result.chartPv"]);
  });

  it("lists every move with its moved flag and a dash for a missing PV change", () => {
    setup(makeResult());

    const table = screen.getByRole("table", { hidden: true });
    const rows = within(table).getAllByRole("row", { hidden: true });
    expect(rows).toHaveLength(4);
    expect(rows[1]).toHaveTextContent("✗ valve.result.moved.no");
    expect(rows[2]).toHaveTextContent("✓ valve.result.moved.yes");
    expect(rows[3]).toHaveTextContent("–");
  });

  it("warns when the PV left its band", () => {
    setup(makeResult({ pv_left_band: true }));

    expect(screen.getByRole("note")).toHaveTextContent("valve.result.pvLeftBand");
  });

  it("calls the two callbacks", () => {
    const { onAgain, onNewPlan } = setup(makeResult());

    fireEvent.click(screen.getByRole("button", { name: "valve.result.again" }));
    fireEvent.click(screen.getByRole("button", { name: "valve.result.newPlan" }));

    expect(onAgain).toHaveBeenCalledTimes(1);
    expect(onNewPlan).toHaveBeenCalledTimes(1);
  });
});

describe("ValveResultView (incomplete result)", () => {
  const INCOMPLETE: Partial<ValveResult> = {
    deadband: null,
    deadband_bracket: null,
    resolution_le: null,
    gain: null,
    sigma_pv: null,
    moves: [],
  };

  it("shows the translated reason for a known code", () => {
    setup(makeResult({ ...INCOMPLETE, reason_code: "no_gain", reason: "flat PV" }));

    expect(screen.getByRole("status")).toHaveTextContent(
      'valve.result.incomplete.no_gain{"message":"flat PV"}',
    );
  });

  it("falls back to the generic text for an unknown code", () => {
    setup(makeResult({ ...INCOMPLETE, reason_code: "weird", reason: "boom" }));

    expect(screen.getByRole("status")).toHaveTextContent('valve.result.incomplete.other{"message":"boom"}');
  });

  it("shows dashes and the none texts where numbers are missing", () => {
    setup(makeResult({ ...INCOMPLETE, reason_code: "no_gain", reason: "x" }));

    expect(valueOf("valve.result.deadband")).toBe("valve.result.deadbandNone");
    expect(valueOf("valve.result.resolution")).toBe("valve.result.resolutionNone");
    expect(valueOf("valve.result.gain")).toBe("–");
    expect(valueOf("valve.result.noise")).toBe("–");
  });

  it("shows the lower bound when only that is known", () => {
    setup(
      makeResult({
        ...INCOMPLETE,
        deadband_lower_bound: 2,
        reason_code: "no_move_after_reversal",
        reason: "x",
      }),
    );

    expect(valueOf("valve.result.deadband")).toBe('valve.result.deadbandAtLeast{"value":"2"}');
  });
});

// src/components/ValvePlanView.test.tsx
// Behaviour tests for ValvePlanView: procedure list, summary and the three actions.

import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ValvePlan } from "../api";
import { ValvePlanView } from "./ValvePlanView";

/** Fake translator: the key plus stringified params. */
const t = (key: string, params?: Record<string, string | number>) =>
  key + (params ? JSON.stringify(params) : "");

/** A small realistic plan: 2 steps, 4 minutes. */
const PLAN: ValvePlan = {
  op_start: 50,
  dwell_s: 120,
  op_low: 0,
  op_high: 100,
  pv_band: 5,
  step_sizes: [1],
  steps_per_leg: [2],
  n_steps: 2,
  total_s: 240,
  steps: [],
  procedure: [
    { code: "manual", params: {} },
    { code: "abort", params: { op_start: 50, pv_band: 5 } },
    { code: "set_start", params: { op: 50, dwell_s: 120 } },
    { code: "step", params: { op: 51, dwell_s: 120 } },
    { code: "return_auto", params: { op: 50 } },
  ],
};

afterEach(() => vi.restoreAllMocks());

/** Renders the view and returns the spies. */
function setup(plan: ValvePlan = PLAN) {
  const onRecord = vi.fn();
  const onBack = vi.fn();
  render(<ValvePlanView plan={plan} onRecord={onRecord} onBack={onBack} t={t} />);
  return { onRecord, onBack };
}

describe("ValvePlanView", () => {
  it("shows the summary with step count and minutes", () => {
    setup();

    expect(screen.getByText('valve.plan.summary{"steps":2,"minutes":"4"}')).toBeInTheDocument();
  });

  it("lists one procedure sentence per step, in order", () => {
    setup();

    const items = within(screen.getByRole("list")).getAllByRole("listitem");
    expect(items).toHaveLength(5);
    expect(items[0]).toHaveTextContent("valve.plan.step.manual");
    expect(items[1]).toHaveTextContent('valve.plan.step.abortBand{"band":"5.00","op":"50.00"}');
    expect(items[3]).toHaveTextContent('valve.plan.step.step{"op":"51.00","dwell":"120"}');
    expect(items[4]).toHaveTextContent('valve.plan.step.return_auto{"op":"50.00"}');
  });

  it("uses the no-band abort sentence when pv_band is null", () => {
    setup({ ...PLAN, procedure: [{ code: "abort", params: { op_start: 50, pv_band: null } }] });

    expect(screen.getByRole("listitem")).toHaveTextContent('valve.plan.step.abort{"op":"50.00"}');
  });

  it("calls onRecord and onBack from the buttons", () => {
    const { onRecord, onBack } = setup();

    fireEvent.click(screen.getByRole("button", { name: "valve.plan.record" }));
    fireEvent.click(screen.getByRole("button", { name: "valve.plan.back" }));

    expect(onRecord).toHaveBeenCalledTimes(1);
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("prints the page and keeps the buttons in a no-print block", () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
    setup();

    const printButton = screen.getByRole("button", { name: "valve.plan.print" });
    fireEvent.click(printButton);

    expect(print).toHaveBeenCalledTimes(1);
    expect(printButton.parentElement).toHaveClass("no-print");
  });
});

// frontend/src/components/EconomicsWhy.test.tsx
/**
 * Unit tests of the "where and why" view and the benefit summary: rates, binding table,
 * the hint without an objective, and the violations count of the economic branch.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ControllerDetail, MpcDiagnostics, MpcEconomicsDiagnostics } from "../controllersApi";
import * as sim from "../mpcSimulatorApi";
import { mockT } from "../tuningTestKit";
import { EconomicsBenefit } from "./EconomicsBenefit";
import { EconomicsWhy } from "./EconomicsWhy";

const economics: MpcEconomicsDiagnostics = {
  status: "solved", value_rate: 120, tracking_rate: 100, benefit_rate: 20, soft_limits_applied: true,
  binding: [{ kind: "MV", variable: "water", side: "upper", limit: "soft", shadow_price: 3.5 }],
};

afterEach(() => vi.restoreAllMocks());

describe("EconomicsWhy", () => {
  it("shows the rates and the binding limits with shadow prices", () => {
    render(<EconomicsWhy economics={economics} currency="EUR" t={mockT} />);
    expect(screen.getByTestId("economics-why").textContent).toContain('"value":"20","unit":"EUR/h"');
    const row = screen.getByTestId("economics-binding").querySelector("tbody tr")!;
    expect(row.textContent).toContain("MV water");
    expect(row.textContent).toContain("side.upper");
    expect(row.textContent).toContain("limit.soft");
    expect(row.textContent).toContain("3.5");
  });

  it("renders only a hint without an objective", () => {
    render(<EconomicsWhy currency="EUR" t={mockT} />);
    expect(screen.getByTestId("economics-why").textContent).toBe("controllers.mpc.economics.noObjective");
  });
});

describe("EconomicsBenefit", () => {
  const detail = {
    id: "M1", variables: [],
    economics: { cv_value: { y: 2 }, mv_cost: { u: 1 }, soft_limits: { y: { hi: 9 } }, source: "operator" },
  } as unknown as ControllerDetail;
  const diagnostics = {
    kind: "mpc",
    cvs: [{ id: "y", lo: 0, hi: 10 }], mvs: [{ id: "u", lo: 0, hi: 5 }],
  } as unknown as MpcDiagnostics;
  const branch = { cvs: [], mvs: [], rate: [], settled_rate: 0, violations: { y: [0, 0] }, binding: [{ kind: "MV", index: 0, side: "upper", limit: "hard", share: 0.6, mean_shadow_price: 2 }] };

  it("sends the model-order objective and shows the summary", async () => {
    const run = vi.spyOn(sim, "simulateBenefit").mockResolvedValue({
      time_s: [0], targets: [1], unit: "currency/h", benefit_rate: 7, value_gained: 42, cv_names: ["y"], mv_names: ["u"],
      tracking: branch, economic: branch,
    });
    render(<EconomicsBenefit detail={detail} diagnostics={diagnostics} t={mockT} />);
    fireEvent.change(screen.getByLabelText("precommission.artifact_id"), { target: { value: "a1" } });
    for (const k of ["move_max", "rate_max", "target_rate", "funnel_start", "funnel_end"]) {
      fireEvent.change(screen.getByLabelText(`precommission.${k}`), { target: { value: "1" } });
    }
    fireEvent.click(screen.getByTestId("economics-benefit-run"));
    await waitFor(() => expect(screen.getByTestId("economics-benefit-result")).toBeTruthy());
    const sent = run.mock.calls[0][0];
    expect(sent.economics).toMatchObject({ cv_value: [2], mv_cost: [1], cv_soft_upper: [9], cv_soft_lower: [null] });
    expect(sent.limits.mv_upper).toEqual([5]);
    expect(screen.getByTestId("economics-violations").textContent).toContain('"n":0');
    expect(screen.getByTestId("economics-violations").textContent).toContain("violationsGood");
    expect(screen.getByTestId("economics-benefit-binding").textContent).toContain('"pct":60');
  });
});

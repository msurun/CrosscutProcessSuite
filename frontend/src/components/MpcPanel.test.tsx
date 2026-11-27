// src/components/MpcPanel.test.tsx
/**
 * Unit tests of the MPC panel of the controller detail (Phase 7.3, #184): limits, targets,
 * relaxed CVs, predicted trajectories, active constraints and the "why no move" reason.
 */

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ControllerDetail as Detail, MpcDiagnostics } from "../controllersApi";
import { mockT } from "../tuningTestKit";
import { ControllerDetail } from "./ControllerDetail";
import { MpcPanel } from "./MpcPanel";

const diagnostics: MpcDiagnostics = {
  kind: "mpc",
  status: "solved",
  reason: "",
  why_no_move: null,
  shed_after: 3,
  cvs: [
    { id: "y1", value: 20, target: 50, lo: 0, hi: 100, relaxed: false, predicted: [20, 25, 31, 38] },
    { id: "y2", value: 99.5, target: null, lo: 0, hi: 100, relaxed: true, predicted: [99.5, 100, 100, 100] },
  ],
  mvs: [
    { id: "u1", sp: 40, proposed: 45, lo: 0, hi: 100, code: "move" },
    { id: "u2", sp: 60, proposed: 60, lo: 0, hi: 60, code: "limit" },
  ],
  active_constraints: [{ kind: "MV", variable: "u2", side: "upper", sample: 1 }],
};

function panel(over: Partial<MpcDiagnostics> = {}) {
  render(<MpcPanel diagnostics={{ ...diagnostics, ...over }} t={mockT} />);
}

describe("MpcPanel", () => {
  it("shows MV and CV limits, targets and the relaxed CV", () => {
    panel();
    expect(within(screen.getByTestId("mpc-mv-u2")).getByText("0 .. 60")).toBeTruthy();
    expect(screen.getByTestId("mpc-mv-u1").textContent).toContain("45");
    expect(screen.getByTestId("mpc-cv-y1").textContent).toContain("50");
    expect(screen.getByTestId("mpc-cv-y1").textContent).toContain("0 .. 100");
    expect(screen.getByTestId("mpc-cv-y2").textContent).toContain("controllers.mpc.relaxed");
    expect(screen.getByTestId("mpc-cv-y1").textContent).not.toContain("controllers.mpc.relaxed");
  });

  it("draws one accessible predicted trajectory per CV", () => {
    panel();
    const chart = screen.getByTestId("mpc-chart-y1");
    expect(chart.getAttribute("role")).toBe("img");
    expect(chart.getAttribute("aria-label")).toContain('"end":"38"');
    expect(chart.querySelectorAll("polyline")).toHaveLength(1);
    expect(chart.querySelectorAll("line")).toHaveLength(3);
    expect(screen.getByTestId("mpc-chart-y2").querySelectorAll("line")).toHaveLength(2);
  });

  it("lists the active constraints", () => {
    panel();
    const list = screen.getByTestId("mpc-constraints");
    expect(list.textContent).toContain("controllers.mpc.constraint.upper");
    expect(list.textContent).toContain('"variable":"u2"');
  });

  it("says no constraint is active when the list is empty", () => {
    panel({ active_constraints: [] });
    expect(screen.getByTestId("mpc-constraints").textContent).toBe("controllers.mpc.noConstraints");
  });

  it("says the controller moves when it does", () => {
    panel();
    expect(screen.getByTestId("mpc-why").textContent).toContain("controllers.mpc.moving");
  });

  it.each(["hold", "shed", "limit", "no_target", "at_target", "input_bad", "bumpless_start"] as const)(
    "names the reason when nothing moves: %s",
    (code) => {
      panel({ why_no_move: code, reason: "primal infeasible" });
      const text = screen.getByTestId("mpc-why").textContent ?? "";
      expect(text).toContain(`controllers.mpc.code.${code}`);
      expect(text).toContain("primal infeasible");
    },
  );

  it("survives a cycle without inputs (no CV rows, no predictions)", () => {
    panel({ cvs: [], mvs: [], why_no_move: "input_bad", status: "input_bad" });
    expect(screen.getByTestId("mpc-panel")).toBeTruthy();
  });
});

describe("ControllerDetail with diagnostics", () => {
  const base = {
    id: "C1", type: "mpc", description: "", cycle_s: 30, state: "advisory", record_unreadable: false,
    reason: "advisory_only", last_cycle_utc: null, last_duration_s: null, overruns: 0,
    consecutive_overruns: 0, liveness_utc: null, last_explanation: "", disabled: [],
    last_advice: null, warnings: null, variables: [],
  } as Detail;

  it("renders the MPC panel only when the record carries MPC diagnostics", () => {
    const props = { canOperate: false, onCommand: () => {}, onSave: () => {}, t: mockT };
    const { rerender } = render(<ControllerDetail detail={{ ...base, diagnostics: null }} {...props} />);
    expect(screen.queryByTestId("mpc-panel")).toBeNull();
    rerender(<ControllerDetail detail={{ ...base, diagnostics }} {...props} />);
    expect(screen.getByTestId("mpc-panel")).toBeTruthy();
  });
});

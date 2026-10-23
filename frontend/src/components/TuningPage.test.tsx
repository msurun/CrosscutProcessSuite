// src/components/TuningPage.test.tsx
// Behaviour tests of the tuning page for integrating loops: model view, refusal reasons, the
// warning banners, the averaging-level inputs and the request they send. The API, the trend
// panes and the window picker are replaced with fakes.

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { IpdtModel, TuningPayload } from "../api";
import type { Translate } from "../findings";
import { makeLoop } from "../testFixtures";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ...actual, fetchTuning: vi.fn(), saveKnowledge: vi.fn() };
});
vi.mock("./TrendPane", () => ({
  TrendPane: (props: { labels: string[] }) => <div role="img" aria-label={props.labels.join("|")} />,
}));
vi.mock("./WindowPicker", () => ({
  WindowPicker: (props: { fitCurve?: unknown }) => (
    <div data-testid="picker" data-fit={props.fitCurve ? "yes" : "no"} />
  ),
}));

import { fetchTuning, saveKnowledge } from "../api";
import { TuningPage } from "./TuningPage";

const fetchMock = vi.mocked(fetchTuning);
const saveMock = vi.mocked(saveKnowledge);
const t: Translate = (key, params) => key + (params ? JSON.stringify(params) : "");

const IPDT: IpdtModel = {
  kind: "ipdt",
  slope_per_s: 0.002,
  delay_s: 20,
  delay_lower_s: 15,
  delay_upper_s: 30,
  delay_used_s: 30,
  r_squared: 0.97,
  slope_rel_se: 0.05,
  up_down_ratio: null,
  baseline_slope: 0,
  verdict: "ok",
  reasons: [],
};

/** An accepted integrating payload; tests override the parts they are about. */
function ipdtPayload(overrides: Partial<TuningPayload> = {}): TuningPayload {
  return {
    loop: "Loop A",
    windows: [],
    window: { start_s: 0, end_s: 1200, manual_percent: 100 },
    warnings: [],
    robustness: 0.5,
    blocked_code: null,
    blocked_reasons: [],
    markdown: "# report",
    model: IPDT,
    fit: { verdict: "good", r_squared: 0.97 },
    check: { t_s: [0, 1], measured: [1, 2], simulated: [1, 2] },
    fit_curve: { t_s: [0, 1], pv_model: [1, 2] },
    settings: { simc: { kc: 12.5, ti_s: 160 }, amigo: null },
    dcs_forms: {},
    tau_c_s: 40,
    invert_control: false,
    step: { t_s: [0, 1], pv: [0, 1], out: [0, 1] },
    ...overrides,
  };
}

async function show(payload: TuningPayload) {
  fetchMock.mockResolvedValue(payload);
  render(<TuningPage datasetId="d" loopName="Loop A" loop={makeLoop({ unit: "%" })} t={t} onBack={() => {}} />);
  await screen.findByText("tuning.step2");
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("integrating model view", () => {
  it("shows ramp slope and dead time, not gain, time constant or the controllability hint", async () => {
    await show(ipdtPayload());
    expect(screen.getByText("tuning.ipdt.slope")).toBeInTheDocument();
    expect(screen.getByText(/tuning\.ipdt\.slopeUnit/)).toBeInTheDocument();
    expect(screen.getByText("tuning.model.delay")).toBeInTheDocument();
    expect(screen.queryByText("tuning.model.gain")).toBeNull();
    expect(screen.queryByText("tuning.model.tau")).toBeNull();
    expect(screen.queryByText("tuning.model.ratio")).toBeNull();
    expect(screen.getByText("tuning.ipdt.explain")).toBeInTheDocument();
  });

  it("shows the dead time as an estimate with its range and states the upper bound is used", async () => {
    await show(ipdtPayload());
    expect(screen.getByText(/tuning\.ipdt\.delayRange.*"lower":"15".*"upper":"30"/)).toBeInTheDocument();
    expect(screen.getByText(/tuning\.recommendation\.ipdt.*"upper":"30"/)).toBeInTheDocument();
    expect(screen.getByText("tuning.ipdt.experimental")).toBeInTheDocument();
    expect(screen.queryByText("tuning.ipdt.delayWide")).toBeNull();
  });

  it("hints at a longer or larger step when the dead-time range is wide", async () => {
    await show(ipdtPayload({ model: { ...IPDT, delay_lower_s: 3, delay_upper_s: 12, delay_used_s: 12 } }));
    expect(screen.getByText("tuning.ipdt.delayWide")).toBeInTheDocument();
  });

  it("draws the fitted ramp over the measured PV in the check chart and the window preview", async () => {
    await show(ipdtPayload());
    expect(screen.getByRole("img", { name: "tuning.check.measured|tuning.check.ramp" })).toBeInTheDocument();
    expect(screen.getByTestId("picker")).toHaveAttribute("data-fit", "yes");
  });

  it("gives the integrating recommendation, the overshoot note and no AMIGO row", async () => {
    await show(ipdtPayload());
    expect(screen.getByText(/tuning\.recommendation\.ipdt.*"tauc":"40"/)).toBeInTheDocument();
    expect(screen.getByText("tuning.ipdt.overshoot")).toBeInTheDocument();
    expect(screen.queryByText("AMIGO")).toBeNull();
    expect(screen.queryByText("tuning.ipdt.reverse")).toBeNull();
  });

  it("hints at a reverse-acting controller when invert_control is true", async () => {
    await show(ipdtPayload({ invert_control: true }));
    expect(screen.getByText("tuning.ipdt.reverse")).toBeInTheDocument();
  });

  it("lists the reasons of a low-confidence fit as a note", async () => {
    const model = { ...IPDT, verdict: "low_confidence" as const, reasons: ["up_down_differ_over_25pct"] };
    await show(ipdtPayload({ model }));
    expect(screen.getByText("tuning.ipdt.lowConfidence")).toBeInTheDocument();
    expect(screen.getByText("tuning.ipdt.reason.up_down_differ_over_25pct")).toBeInTheDocument();
  });

  it("keeps the first-order view for a self-regulating model", async () => {
    const model = { kind: "fopdt" as const, gain: 1.5, time_constant_s: 60, delay_s: 5 };
    const settings = { simc: { kc: 1, ti_s: 2 }, amigo: { kc: 1, ti_s: 2 } };
    await show(ipdtPayload({ model, fit_curve: undefined, tau_c_s: undefined, settings }));
    expect(screen.getByText("tuning.model.gain")).toBeInTheDocument();
    expect(screen.getByText("tuning.model.ratio")).toBeInTheDocument();
    expect(screen.queryByText("tuning.ipdt.slope")).toBeNull();
    expect(screen.getByText("AMIGO")).toBeInTheDocument();
  });
});

describe("refusal view", () => {
  const refused = [
    "r2_below_0.8",
    "pre_move_lead_under_20pct",
    "post_move_too_short",
    "theta_on_grid_edge",
    "no_out_move",
  ];

  it("lists every reason with what to do about it and withholds the settings", async () => {
    const model = { ...IPDT, verdict: "blocked" as const, reasons: refused };
    const payload = ipdtPayload({ blocked_code: "ipdt_refused", blocked_reasons: refused, model, settings: null, step: null });
    await show(payload);
    expect(screen.getByText("tuning.blocked.ipdt_refused")).toBeInTheDocument();
    for (const code of refused) {
      expect(screen.getByText(`tuning.ipdt.reason.${code}`)).toBeInTheDocument();
      expect(screen.getByText(`tuning.ipdt.action.${code}`)).toBeInTheDocument();
    }
    expect(screen.queryByText(/tuning\.recommendation/)).toBeNull();
  });

  it("falls back to the generic text for an unknown reason code", async () => {
    const payload = ipdtPayload({ blocked_code: "ipdt_refused", blocked_reasons: ["brand_new"], settings: null, step: null });
    await show(payload);
    expect(screen.getByText("tuning.ipdt.reason.unknown")).toBeInTheDocument();
  });
});

describe("warnings", () => {
  it("shows closed_loop_data as before", async () => {
    await show(ipdtPayload({ warnings: [{ code: "closed_loop_data" }] }));
    expect(screen.getByText("tuning.warning.closed_loop_data")).toBeInTheDocument();
  });

  it("shows an info banner for looks_self_regulating", async () => {
    await show(ipdtPayload({ warnings: [{ code: "looks_self_regulating", fopdt_r_squared: 0.93 }] }));
    expect(screen.getByText(/tuning\.warning\.looks_self_regulating.*0\.93/)).toBeInTheDocument();
  });

  it("offers looks_integrating with a confirmed save of the process kind and then refetches", async () => {
    const warning = {
      code: "looks_integrating" as const,
      reason: "time_constant_over_3x_window" as const,
      time_constant_s: 5000,
      ipdt_r_squared: null,
    };
    await show(ipdtPayload({ warnings: [warning] }));
    fireEvent.click(screen.getByRole("button", { name: "tuning.warning.setIntegrating" }));
    expect(saveMock).not.toHaveBeenCalled(); // asks for confirmation first
    saveMock.mockResolvedValue({} as never);
    fireEvent.click(screen.getByRole("button", { name: "tuning.warning.setIntegratingYes" }));
    await waitFor(() => expect(saveMock).toHaveBeenCalledWith("d", "Loop A", { process_kind: "integrating" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it("can cancel the confirmation without saving", async () => {
    const warning = {
      code: "looks_integrating" as const,
      reason: "model_failed_ipdt_fits" as const,
      time_constant_s: null,
      ipdt_r_squared: 0.9,
    };
    await show(ipdtPayload({ warnings: [warning] }));
    fireEvent.click(screen.getByRole("button", { name: "tuning.warning.setIntegrating" }));
    fireEvent.click(screen.getByRole("button", { name: "tuning.warning.setIntegratingNo" }));
    expect(saveMock).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "tuning.warning.setIntegrating" })).toBeInTheDocument();
  });
});

describe("averaging level inputs", () => {
  const maxLabel = /tuning\.swing\.max/;
  const loadLabel = "tuning.swing.load";

  it("sends max_swing and load_step_pct only when both are valid, and shows tau_c", async () => {
    await show(ipdtPayload());
    fireEvent.change(screen.getByLabelText(maxLabel), { target: { value: "2" } });
    expect(screen.getByRole("alert")).toHaveTextContent("tuning.swing.invalid.both");
    fireEvent.change(screen.getByLabelText(loadLabel), { target: { value: "4" } });
    await waitFor(() =>
      expect(fetchMock).toHaveBeenLastCalledWith("d", "Loop A", expect.objectContaining({ maxSwing: 2, loadStepPct: 4 })),
    );
    expect(screen.getByText(/tuning\.swing\.result.*"tauc":"40"/)).toBeInTheDocument();
    for (const call of fetchMock.mock.calls.slice(0, -1)) {
      expect(call[2]).not.toHaveProperty("maxSwing");
    }
  });

  it("flags non-positive values and does not send them", async () => {
    await show(ipdtPayload());
    fireEvent.change(screen.getByLabelText(maxLabel), { target: { value: "-1" } });
    fireEvent.change(screen.getByLabelText(loadLabel), { target: { value: "4" } });
    expect(screen.getByRole("alert")).toHaveTextContent("tuning.swing.invalid.positive");
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(fetchMock.mock.calls.every((call) => !("maxSwing" in (call[2] ?? {})))).toBe(true);
  });

  it("is not shown for a self-regulating model", async () => {
    const model = { kind: "fopdt" as const, gain: 1, time_constant_s: 10, delay_s: 1 };
    await show(ipdtPayload({ model, settings: null }));
    expect(screen.queryByText("tuning.swing.title")).toBeNull();
  });
});

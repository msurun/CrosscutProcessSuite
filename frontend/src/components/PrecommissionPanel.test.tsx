// Exercise the read-only comparison form, model traces and validation refusals.
// Responses use the simulator's nested constraint counters rather than a chart-only mock.
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { translate } from "../i18n";
import { LIMIT_FIELDS, type SimulationResult } from "../mpcSimulatorApi";
import { PrecommissionPanel } from "./PrecommissionPanel";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const t = (key: string, params?: Record<string, string | number>) => translate("en", key, params);
const trace = { cvs: [[0], [0.5], [1]], mvs: [[0], [1], [0.5]],
  kpis: { iae: [1.5], overshoot: [0], settling_time_s: [null], mv_travel: [1.5],
    constraint_violations: { cv: [0], mv: [0], move: [0], rate: [0] } } };
const RESULT: SimulationResult = { time_s: [0, 1, 2], targets: [[0], [1], [1]], disturbances: [[], [], []],
  mpc: trace, pid: trace, cv_names: ["purity"], mv_names: ["reflux"],
  limits: { mv_lower: [-1], mv_upper: [1], cv_lower: [-2], cv_upper: [2] } };

/** Supply all engineering limits and an explicit current-PID snapshot. */
function fillForm() {
  const fill = (key: string, value: string) => fireEvent.change(screen.getByLabelText(t(`precommission.${key}`)), { target: { value } });
  fill("artifact_id", "identified-model"); fill("controller_id", "C1");
  LIMIT_FIELDS.forEach((key) => fill(key, key.endsWith("lower") ? "-2" : "2"));
  fill("loop_id", "LA"); fill("kp", "0.2"); fill("ti_s", "60"); fill("td_s", "0");
}

it("sends only the simulation request and renders both controllers, limits and all KPI counters", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(RESULT)));
  vi.stubGlobal("fetch", fetch);
  render(<PrecommissionPanel t={t} />);
  expect(fetch).not.toHaveBeenCalled();
  fillForm();
  fireEvent.click(screen.getByRole("button", { name: t("precommission.run") }));
  expect(await screen.findByRole("table")).toHaveTextContent("MV rate violations");
  expect(screen.getAllByRole("img")).toHaveLength(2);
  expect(screen.getByRole("img", { name: /purity/ }).querySelectorAll("polyline")).toHaveLength(5);
  expect(screen.getByRole("table")).toHaveTextContent("Not settled");
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0][0]).toBe("/api/mpc/simulate");
  expect(JSON.parse(fetch.mock.calls[0][1].body).pid_tunings).toEqual([{ loop_id: "LA", kp: 0.2, ti_s: 60, td_s: 0, cv_index: 0 }]);
});

it("shows API permission failures without leaving comparison results", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "forbidden" }), { status: 403 })));
  render(<PrecommissionPanel t={t} />); fillForm();
  fireEvent.click(screen.getByRole("button", { name: t("precommission.run") }));
  expect(await screen.findByRole("alert")).toHaveTextContent("forbidden");
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});

it("clears stale results when a different scenario is selected", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(RESULT))));
  render(<PrecommissionPanel t={t} />); fillForm();
  fireEvent.click(screen.getByRole("button", { name: t("precommission.run") }));
  await screen.findByRole("table");
  fireEvent.change(screen.getByLabelText(t("precommission.scenario")), { target: { value: "dv_step" } });
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});

it.each(["en", "pl", "es"])("translates every visible field in %s without replacement characters", (language) => {
  const messages = (key: string, params?: Record<string, string | number>) => translate(language, key, params);
  render(<PrecommissionPanel t={messages} />);
  const panel = screen.getByRole("region", { name: messages("precommission.title") });
  expect(panel.textContent).not.toContain("?");
  expect(panel.textContent).not.toContain("precommission.");
  expect(within(panel).getByLabelText(messages("precommission.kp"))).toHaveValue(null);
});

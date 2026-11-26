// Verify the planner panel: nothing is sent before an explicit preview and confirm, the confirm
// carries the previewed digest, refusals are shown, and the abort button reaches the API.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { translate } from "../i18n";
import { StepPlanPanel } from "./StepPlanPanel";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const t = (key: string, params?: Record<string, string | number>) => translate("en", key, params);
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const STEP = { index: 0, mv: "mva", tag: "a.sp", at_s: 0, value: 53 };
const PREVIEW = { ok: true, digest: "d".repeat(64), steps: [STEP], refusals: [], gateway_mode: "confirm" };
const RECORD = { id: "p1", status: "running", steps: [{ ...STEP, status: "queued" }], abort_reason: null, displaced: [] };

/** Fill one MV row and the duration with explicit values. */
function fill() {
  fireEvent.change(screen.getByLabelText("Controller id"), { target: { value: "C1" } });
  fireEvent.change(screen.getByLabelText("MV variable id"), { target: { value: "mva" } });
  fireEvent.change(screen.getByLabelText("Signed amplitude (engineering units)"), { target: { value: "3" } });
  fireEvent.change(screen.getByLabelText(/^Duration/), { target: { value: "120" } });
}

it("needs a preview before confirm and sends the previewed digest", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(json(PREVIEW)).mockResolvedValueOnce(json(RECORD));
  vi.stubGlobal("fetch", fetch);
  render(<StepPlanPanel t={t} />);
  expect(screen.getByRole("button", { name: "Confirm and propose steps" })).toBeDisabled();
  fill();
  fireEvent.click(screen.getByRole("button", { name: "Preview plan" }));
  await screen.findByText("Planned setpoint steps");
  expect(fetch.mock.calls[0][0]).toBe("/api/mpc/step-plans/preview");
  fireEvent.click(screen.getByRole("button", { name: "Confirm and propose steps" }));
  await screen.findByText(/Plan state: running/);
  const body = JSON.parse(fetch.mock.calls[1][1].body);
  expect(body.digest).toBe(PREVIEW.digest);
  expect(body.mvs).toEqual([{ controller_id: "C1", variable_id: "mva", amplitude: 3 }]);
  expect(screen.getByText("waiting for approval")).toBeInTheDocument();
});

it("shows refusal reasons and keeps confirm disabled", async () => {
  const refused = { ok: false, digest: null, steps: [], gateway_mode: "confirm",
    refusals: [{ mv: "mva", code: "interval_below_min", step: 1, detail: "t=30s" }] };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(refused)));
  render(<StepPlanPanel t={t} />);
  fill();
  fireEvent.click(screen.getByRole("button", { name: "Preview plan" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("closer than the policy minimum interval");
  expect(screen.getByRole("button", { name: "Confirm and propose steps" })).toBeDisabled();
});

it("blocks confirm when the gateway is not in confirm mode", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ ...PREVIEW, gateway_mode: "supervised" })));
  render(<StepPlanPanel t={t} />);
  fill();
  fireEvent.click(screen.getByRole("button", { name: "Preview plan" }));
  await screen.findByText("The Write Gateway is not in confirm mode, so the plan cannot start.");
  expect(screen.getByRole("button", { name: "Confirm and propose steps" })).toBeDisabled();
});

it("aborts a running plan and lists displaced setpoints", async () => {
  const aborted = { ...RECORD, status: "aborted", abort_reason: "operator_abort",
    displaced: [{ tag: "a.sp", baseline: 50, last_applied: 53 }] };
  const fetch = vi.fn().mockResolvedValueOnce(json(PREVIEW)).mockResolvedValueOnce(json(RECORD))
    .mockResolvedValueOnce(json(aborted));
  vi.stubGlobal("fetch", fetch);
  render(<StepPlanPanel t={t} />);
  fill();
  fireEvent.click(screen.getByRole("button", { name: "Preview plan" }));
  await screen.findByText("Planned setpoint steps");
  fireEvent.click(screen.getByRole("button", { name: "Confirm and propose steps" }));
  await screen.findByText(/Plan state: running/);
  fireEvent.click(screen.getByRole("button", { name: "Abort plan" }));
  await waitFor(() => expect(fetch.mock.calls[2][0]).toBe("/api/mpc/step-plans/p1/abort"));
  expect(await screen.findByText(/a.sp: 53/)).toBeInTheDocument();
});

it.each(["en", "pl", "es"])("shows translated safety text in %s", (language) => {
  render(<StepPlanPanel t={(key, params) => translate(language, key, params)} />);
  expect(screen.getByRole("heading")).toHaveTextContent(translate(language, "stepPlan.title"));
  expect(screen.getByText(translate(language, "stepPlan.notice"))).toBeInTheDocument();
});

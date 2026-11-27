// Component tests of the Runtime panel: good output, bad output with reason, events and the empty
// states, a mode change and the exact refusal text in a role=alert region (en and pl).
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { translate } from "../i18n";
import type { RuntimeOutput, SoftSensorRuntime as Runtime } from "../softsensorRuntime";
import { SoftSensorRuntime } from "./SoftSensorRuntime";

const t = (key: string, params?: Record<string, string | number>) => translate("en", key, params);
const URL_BASE = "/api/softsensor/s1";
const REFUSAL = "Deployment refused: no validated advantage over the available lab baseline.";

const OUTPUT: RuntimeOutput = {
  t_utc: "2026-11-27T09:00:00Z", value: 12.5, status: "good", reason: "", source: "instrument", used_downstream: false,
  estimate: 12.4, bias: 0.1, drift: false, effective_mode: "shadow",
};
const GOOD: Runtime = {
  sensor_id: "s1", mode: "shadow", changed_by: "op", changed_utc: "2026-11-27T08:00:00Z",
  output: OUTPUT,
  last_lab: { sample_utc: "2026-11-27T07:00:00Z", lab: 12, estimate: 12.4, residual: -0.4 },
  events: [],
  gate: { available: true, deploy: true, skill: 0.31, reasons: ["skill above baseline"], message: "" },
};
const BAD: Runtime = {
  ...GOOD, mode: "primary",
  output: { ...OUTPUT, value: null, status: "bad", reason: "extrapolation", source: "softsensor", used_downstream: true },
  last_lab: null,
  events: [
    { t_utc: "2026-11-27T08:00:00Z", from: "instrument", to: "softsensor", reason: "frozen" },
    { t_utc: "2026-11-27T08:30:00Z", from: "softsensor", to: "instrument", reason: "measurement_valid" },
  ],
  gate: { available: true, deploy: false, skill: null, reasons: ["no skill"], message: "Gate closed" },
};

/** Stubs fetch: GET runtime answers `state`; PUT mode answers `put` (status and body). */
function stub(state: Runtime, put?: { status: number; body: unknown }) {
  const mock = vi.fn((url: string, init?: RequestInit) => {
    const isPut = init?.method === "PUT";
    const answer = isPut && put !== undefined ? put : { status: 200, body: state };
    if (url !== `${URL_BASE}/${isPut ? "mode" : "runtime"}`) return Promise.reject(new Error(`unexpected ${url}`));
    return Promise.resolve(new Response(JSON.stringify(answer.body), { status: answer.status }));
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("SoftSensorRuntime", () => {
  it("shows a good output, the lab residual, no events and the gate", async () => {
    stub(GOOD);
    render(<SoftSensorRuntime sid="s1" t={t} />);
    expect(await screen.findByTestId("soft-rt-value")).toHaveTextContent("12.500");
    expect(screen.getByTestId("soft-rt-status")).toHaveTextContent("[OK] Good");
    expect(screen.getByTestId("soft-rt-downstream")).toHaveTextContent("Used downstream: no");
    expect(screen.getByTestId("soft-rt-lab")).toHaveTextContent("residual -0.400");
    expect(screen.getByTestId("soft-rt-no-events")).toHaveTextContent("No failover events.");
    expect(screen.getByTestId("soft-rt-gate")).toHaveTextContent("Deploy allowed: yes; skill: 0.31");
    expect(screen.getByText("skill above baseline")).toBeInTheDocument();
  });

  it("shows a bad output with its reason, newest event first and an empty lab state", async () => {
    stub(BAD);
    render(<SoftSensorRuntime sid="s1" t={t} />);
    expect(await screen.findByTestId("soft-rt-status")).toHaveTextContent("[X] Bad");
    expect(screen.getByTestId("soft-rt-value")).toHaveTextContent("--");
    expect(screen.getByTestId("soft-rt-reason")).toHaveTextContent("extrapolation");
    expect(screen.getByTestId("soft-rt-downstream")).toHaveTextContent("yes");
    expect(screen.getByTestId("soft-rt-no-lab")).toBeInTheDocument();
    const items = within(screen.getByTestId("soft-rt-events")).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("virtual sensor to instrument (measurement_valid)");
    expect(items[1]).toHaveTextContent("instrument to virtual sensor (frozen)");
    expect(screen.getByTestId("soft-rt-gate")).toHaveTextContent("Deploy allowed: no; skill: --");
  });

  it("applies a mode and shows the returned state", async () => {
    const mock = stub(GOOD, { status: 200, body: { ...GOOD, mode: "backup" } });
    render(<SoftSensorRuntime sid="s1" t={t} />);
    await screen.findByTestId("soft-rt-value");
    const apply = screen.getByRole("button", { name: "Apply" });
    expect(apply).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Operating mode"), { target: { value: "backup" } });
    fireEvent.click(apply);
    await waitFor(() => expect(screen.getByTestId("soft-rt-current")).toHaveTextContent("Backup"));
    const put = mock.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({ mode: "backup" });
  });

  it("shows the exact refusal text in an alert", async () => {
    stub(GOOD, { status: 409, body: { detail: REFUSAL } });
    render(<SoftSensorRuntime sid="s1" t={t} />);
    await screen.findByTestId("soft-rt-value");
    fireEvent.change(screen.getByLabelText("Operating mode"), { target: { value: "primary" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(REFUSAL);
    expect(screen.getByTestId("soft-rt-current")).toHaveTextContent("Shadow");
  });

  it("is translated to Polish", async () => {
    stub(GOOD);
    render(<SoftSensorRuntime sid="s1" t={(k, p) => translate("pl", k, p)} />);
    expect(await screen.findByTestId("soft-rt-status")).toHaveTextContent("Dobra");
    expect(screen.getByRole("button", { name: "Zastosuj" })).toBeInTheDocument();
  });
});

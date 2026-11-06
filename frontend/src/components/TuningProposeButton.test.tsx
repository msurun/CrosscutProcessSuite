// frontend/src/components/TuningProposeButton.test.tsx
// "Propose write to DCS": enabled only with gw.propose, a live loop_kpi job and a running gateway;
// sends the proposal body and links to the Tuning view; shows gateway refusals.

import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import * as gatewayApi from "../gatewayApi";
import * as tuningApi from "../tuningApi";
import { makeProposal, mockT, renderAs } from "../tuningTestKit";
import { TuningProposeButton, type ProposeContext } from "./TuningProposeButton";

const ctx: ProposeContext = {
  datasetId: "mill",
  loopName: "FIC101",
  vendor: null,
  window: { start_s: 10, end_s: 600 },
  robustness: 0.5,
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function setup(opts: { gateway?: "ok" | "down" | "off"; job?: boolean; running?: boolean } = {}) {
  const { gateway = "ok", job = true, running = true } = opts;
  const mode = gateway === "off" ? "off" : "confirm";
  const status = vi.spyOn(gatewayApi, "fetchGatewayStatus");
  if (gateway === "down") status.mockRejectedValue(new gatewayApi.GatewayApiError(503, "gateway not running"));
  else status.mockResolvedValue({ mode, targets: {}, pending: 0 });
  vi.spyOn(api, "fetchRuntimeStatus").mockResolvedValue({
    service: { running, updated_at_utc: null },
    jobs: [{ id: "kpi1", kind: "loop_kpi", source: "s", enabled: true, status: "ok", last_run_utc: null, error: null, samples: 0, kpi: null }],
  });
  vi.spyOn(api, "fetchRuntimeJobs").mockResolvedValue({
    schema_version: 1,
    jobs: [{ id: "kpi1", kind: "loop_kpi", source: "s", loops: job ? ["FIC101"] : ["OTHER"], period_s: 60, window_s: 3600, enabled: true }],
  });
}

const button = () => screen.getByTestId("tuning-propose-button");

async function show(role: string) {
  await renderAs(role, <TuningProposeButton ctx={ctx} t={mockT} />, role, "tuning-propose");
}

describe("availability", () => {
  it("is enabled for an engineer with a live job and a running gateway", async () => {
    setup();
    await show("engineer");
    await waitFor(() => expect(button()).not.toHaveAttribute("aria-disabled"));
  });

  it("is disabled with the permission reason for a viewer", async () => {
    setup();
    await show("viewer");
    expect(button()).toHaveAttribute("aria-disabled", "true");
  });

  it.each([
    ["noJob", { job: false }, "tuning.propose.reason.noJob"],
    ["noGateway", { gateway: "down" as const }, "tuning.propose.reason.noGateway"],
    ["gatewayOff", { gateway: "off" as const }, "tuning.propose.reason.gatewayOff"],
    ["service stopped", { running: false }, "tuning.propose.reason.noJob"],
  ])("is disabled with a reason: %s", async (_name, opts, key) => {
    setup(opts);
    await show("engineer");
    await waitFor(() => expect(screen.getByTestId("disabled-reason-text")).toHaveTextContent(key));
    expect(button()).toHaveAttribute("aria-disabled", "true");
  });
});

describe("dialog", () => {
  async function openDialog() {
    setup();
    await show("engineer");
    await waitFor(() => expect(button()).not.toHaveAttribute("aria-disabled"));
    fireEvent.click(button());
    await screen.findByTestId("tuning-propose-dialog");
  }

  it("needs a reason, asks for the vendor form and posts the window", async () => {
    await openDialog();
    const create = vi.spyOn(tuningApi, "createTuningProposal").mockResolvedValue(makeProposal());
    fireEvent.click(screen.getByTestId("tuning-propose-submit"));
    expect(create).not.toHaveBeenCalled();
    fireEvent.change(screen.getByTestId("tuning-propose-vendor"), { target: { value: "abb_pidcc" } });
    fireEvent.change(screen.getByTestId("tuning-propose-method"), { target: { value: "amigo" } });
    fireEvent.change(screen.getByTestId("tuning-propose-reason"), { target: { value: " tune " } });
    fireEvent.click(screen.getByTestId("tuning-propose-submit"));
    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(create).toHaveBeenCalledWith("FIC101", {
      vendor_form: "abb_pidcc",
      method: "amigo",
      reason: "tune",
      dataset_id: "mill",
      start_s: 10,
      end_s: 600,
      robustness: 0.5,
    });
    expect(await screen.findByTestId("tuning-propose-link")).toHaveAttribute("href", "#/d/mill/tuning");
  });

  it("shows a refusal of the gateway as a warning with the mapped message", async () => {
    await openDialog();
    vi.spyOn(tuningApi, "createTuningProposal").mockResolvedValue(makeProposal({ status: "refused:loop_busy" }));
    fireEvent.change(screen.getByTestId("tuning-propose-reason"), { target: { value: "x" } });
    fireEvent.click(screen.getByTestId("tuning-propose-submit"));
    expect(await screen.findByTestId("tuning-propose-result")).toHaveTextContent("tuning.err.loop_busy");
  });

  it("shows an API error such as a missing live value", async () => {
    await openDialog();
    vi.spyOn(tuningApi, "createTuningProposal").mockRejectedValue(new tuningApi.TuningApiError(409, "no_live_values", ""));
    fireEvent.change(screen.getByTestId("tuning-propose-reason"), { target: { value: "x" } });
    fireEvent.click(screen.getByTestId("tuning-propose-submit"));
    expect(await screen.findByTestId("tuning-propose-error")).toHaveTextContent("tuning.err.no_live_values");
  });
});

// src/components/ControllersPage.test.tsx
/**
 * Unit tests of the Controllers view (Phase 2.5, step 7): the list and the detail render,
 * the buttons call the API, a viewer sees no buttons, and a 422 is shown line by line.
 */

import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../controllersApi";
import { renderAs, mockT } from "../tuningTestKit";
import { ControllersPage } from "./ControllersPage";

const summary: api.ControllerSummary = {
  id: "C1",
  type: "fuzzy",
  description: "",
  cycle_s: 30,
  state: "on",
  reason: "running",
  last_cycle_utc: "2026-01-01T00:00:00+00:00",
  last_duration_s: 0.2,
  overruns: 2,
  consecutive_overruns: 1,
  liveness_utc: "2026-01-01T00:00:01+00:00",
  last_explanation: "mv1: +1",
  disabled: [],
};

const detail: api.ControllerDetail = {
  ...summary,
  variables: [
    {
      id: "mv1", role: "MV", binding: { loop: "L1" }, enabled: true,
      limits: { eng: { lo: 0, hi: 100 }, operator: { lo: 10, hi: 90 }, operator_catalogue: { lo: 10, hi: 90 } },
      status: "good", reasons: [], value: 42, sp_value: 40, source_utc: null,
    },
    {
      id: "cv1", role: "CV", binding: { tag: "t.cv" }, enabled: true,
      limits: { operator_catalogue: null },
      status: "bad", reasons: ["stale"], value: 4.5, sp_value: null, source_utc: null,
    },
  ],
};

function mockApi() {
  vi.spyOn(api, "fetchControllers").mockResolvedValue([summary]);
  vi.spyOn(api, "fetchController").mockResolvedValue(detail);
  return {
    command: vi.spyOn(api, "sendControllerCommand").mockResolvedValue(undefined),
    put: vi.spyOn(api, "putControllerVariable").mockResolvedValue(detail),
  };
}

async function openAs(role: string) {
  await renderAs(role, <ControllersPage t={mockT} />, role, "controllers-page");
  fireEvent.click(await screen.findByTestId("controller-open-C1"));
  await screen.findByTestId("controllers-detail");
}

describe("ControllersPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the row and the variables with status and reasons", async () => {
    mockApi();
    await openAs("operator");
    expect(screen.getByTestId("controller-row-C1")).toHaveTextContent("mv1: +1");
    expect(screen.getByTestId("controller-row-C1")).toHaveTextContent("1 / 2");
    expect(screen.getByTestId("controller-var-cv1")).toHaveTextContent("stale");
    expect(screen.getByTestId("controller-var-mv1")).toHaveTextContent("0 .. 100");
  });

  it("sends On, Standby and Off for the selected controller", async () => {
    const { command } = mockApi();
    await openAs("operator");
    fireEvent.click(screen.getByTestId("controller-on"));
    fireEvent.click(screen.getByTestId("controller-standby"));
    fireEvent.click(screen.getByTestId("controller-off"));
    await waitFor(() => expect(command).toHaveBeenCalledTimes(3));
    expect(command.mock.calls.map((call) => call[1])).toEqual(["switch_on", "standby", "switch_off"]);
    expect(screen.getByTestId("controller-off")).not.toHaveAttribute("aria-disabled", "true");
  });

  it("toggles a variable and saves an operator range", async () => {
    const { put } = mockApi();
    await openAs("engineer");
    fireEvent.click(screen.getByTestId("controller-enabled-cv1"));
    await waitFor(() => expect(put).toHaveBeenCalledWith("C1", "cv1", { enabled: false }));
    fireEvent.change(screen.getByTestId("controller-lo-mv1"), { target: { value: "20" } });
    fireEvent.click(screen.getByTestId("controller-save-mv1"));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("C1", "mv1", { enabled: true, operator: { lo: 20, hi: 90 } }),
    );
  });

  it("gives a viewer the data and no buttons or inputs", async () => {
    mockApi();
    await openAs("viewer");
    expect(screen.queryByTestId("controller-commands")).toBeNull();
    expect(screen.queryByTestId("controller-on")).toBeNull();
    expect(screen.queryByTestId("controller-save-mv1")).toBeNull();
    expect(screen.getByTestId("controller-enabled-mv1")).toBeDisabled();
    expect(screen.getByTestId("controller-var-mv1")).toHaveTextContent("10 .. 90");
  });

  it("lists the problems of a 422 line by line", async () => {
    const { put } = mockApi();
    put.mockRejectedValue(new api.ControllersApiError(422, ["operator.lo must be below operator.hi", "outside eng"]));
    await openAs("operator");
    fireEvent.click(screen.getByTestId("controller-save-mv1"));
    const alert = await screen.findByTestId("controllers-error");
    expect(alert).toHaveTextContent("operator.lo must be below operator.hi");
    expect(alert.querySelectorAll("li")).toHaveLength(2);
  });
});

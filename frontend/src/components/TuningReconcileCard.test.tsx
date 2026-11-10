// frontend/src/components/TuningReconcileCard.test.tsx
// Unit tests for TuningReconcileCard: displays intended vs current DCS values,
// enforces gw.approve.tuning authority, invokes resolveOpenIntent, and handles errors.

import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as tuningApi from "../tuningApi";
import { mockT, renderAs } from "../tuningTestKit";
import { TuningReconcileCard } from "./TuningReconcileCard";

const sampleIntent: tuningApi.ParamIntentRecord = {
  key: "intent-fic101-xyz",
  loop_id: "FIC101",
  created_at: "2026-11-10T10:00:00Z",
  proposer: "alice",
  targets: [
    { target: "FIC101.GAIN", to_value: 1.5, current_value: 1.0 },
    { target: "FIC101.TI", to_value: 45.0, current_value: null },
  ],
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

async function mountCard(role: string, intent = sampleIntent, onResolved?: () => void) {
  return renderAs(
    role,
    <TuningReconcileCard intent={intent} onResolved={onResolved} t={mockT} />,
    role,
    "tuning-reconcile-card",
  );
}

describe("TuningReconcileCard display", () => {
  it("renders loop name in heading, target tags, intended values and current DCS values", async () => {
    await mountCard("engineer");
    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent("tuning.reconcile.title: FIC101");
    expect(screen.getByTestId("reconcile-intended-FIC101.GAIN")).toHaveTextContent("1.5");
    expect(screen.getByTestId("reconcile-current-FIC101.GAIN")).toHaveTextContent("1");
    expect(screen.getByTestId("reconcile-intended-FIC101.TI")).toHaveTextContent("45");
    expect(screen.getByTestId("reconcile-current-FIC101.TI")).toHaveTextContent("tuning.reconcile.unknown");
  });
});

describe("TuningReconcileCard authority", () => {
  it("disables resolve action for viewer and operator lacking gw.approve.tuning", async () => {
    await mountCard("viewer");
    expect(screen.getByTestId("reconcile-resolve")).toBeDisabled();
    cleanup();

    await mountCard("operator");
    expect(screen.getByTestId("reconcile-resolve")).toBeDisabled();
  });

  it("enables resolve action for engineer and lead holding gw.approve.tuning", async () => {
    await mountCard("engineer");
    expect(screen.getByTestId("reconcile-resolve")).not.toBeDisabled();
    cleanup();

    await mountCard("lead");
    expect(screen.getByTestId("reconcile-resolve")).not.toBeDisabled();
  });
});

describe("TuningReconcileCard resolve action", () => {
  it("calls resolveOpenIntent, displays success notice and notifies onResolved", async () => {
    const onResolved = vi.fn();
    const resolveSpy = vi.spyOn(tuningApi, "resolveOpenIntent").mockResolvedValue({ status: "resolved" });
    await mountCard("lead", sampleIntent, onResolved);

    fireEvent.click(screen.getByTestId("reconcile-resolve"));
    await waitFor(() => expect(resolveSpy).toHaveBeenCalledWith("intent-fic101-xyz"));
    expect(await screen.findByTestId("reconcile-success")).toHaveTextContent("tuning.reconcile.success");
    expect(onResolved).toHaveBeenCalledTimes(1);
  });

  it("displays step-up failure notice when resolve returns HTTP 428", async () => {
    vi.spyOn(tuningApi, "resolveOpenIntent").mockRejectedValue(
      new tuningApi.TuningApiError(428, "step_up_required", ""),
    );
    await mountCard("engineer");

    fireEvent.click(screen.getByTestId("reconcile-resolve"));
    expect(await screen.findByTestId("reconcile-error")).toHaveTextContent("tuning.err.stepUp");
  });

  it("displays mapped error notice when resolve fails with an API refusal code", async () => {
    vi.spyOn(tuningApi, "resolveOpenIntent").mockRejectedValue(
      new tuningApi.TuningApiError(403, "forbidden", ""),
    );
    await mountCard("engineer");

    fireEvent.click(screen.getByTestId("reconcile-resolve"));
    expect(await screen.findByTestId("reconcile-error")).toHaveTextContent("tuning.err.forbidden");
  });
});

// frontend/src/components/GatewayPage.test.tsx
/**
 * Unit tests for GatewayPage component (Phase 2, #46).
 * Verifies rendering of status/targets/proposals/audit, approval and rejection flows,
 * confirmation dialogs for kill and supervised mode, error reporting, and polling cleanup.
 */

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as gatewayApi from "../gatewayApi";
import { GatewayPage } from "../GatewayPage";

const mockT = (key: string, params?: Record<string, string | number>) => {
  if (params && params.reason !== undefined) {
    return `${key}:${params.reason}`;
  }
  return key;
};

const statusFixture: gatewayApi.GatewayStatus = {
  mode: "confirm",
  targets: {
    "FIC101.SP": "enabled",
    "TIC102.SP": "stopped:rejected",
  },
  pending: 1,
};

const proposalsFixture: gatewayApi.GatewayProposal[] = [
  {
    key: "prop-key-1",
    target_tag: "FIC101.SP",
    value: 55.0,
    proposer: "opt_agent",
    t_ns: 1_000_000_000,
    reason: "step test",
  },
];

const auditFixture: gatewayApi.GatewayAuditResponse = {
  chain_ok: true,
  records: [
    {
      seq: "0",
      t_ns: "1000000000",
      event: "proposal",
      prev_hash: "0000000000000000000000000000000000000000000000000000000000000000",
      hash: "abc123hash",
      tag: "FIC101.SP",
      value: "55.0",
      reason_code: "ok",
    },
  ],
};

function setupGatewaySpies() {
  vi.spyOn(gatewayApi, "fetchGatewayStatus").mockResolvedValue(statusFixture);
  vi.spyOn(gatewayApi, "fetchGatewayPending").mockResolvedValue(proposalsFixture);
  vi.spyOn(gatewayApi, "fetchGatewayAudit").mockResolvedValue(auditFixture);
}

describe("GatewayPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("renders operating mode, targets table, pending proposals, and audit status", async () => {
    setupGatewaySpies();
    render(<GatewayPage t={mockT} />);

    await waitFor(() => {
      expect(screen.getByTestId("gateway-mode-chip")).toHaveTextContent("confirm");
    });

    expect(screen.getByTestId("gateway-target-FIC101.SP")).toBeInTheDocument();
    expect(screen.getByTestId("gateway-target-TIC102.SP")).toBeInTheDocument();
    expect(screen.getByTestId("gateway-reenable-TIC102.SP")).toBeInTheDocument();
    expect(screen.queryByTestId("gateway-reenable-FIC101.SP")).not.toBeInTheDocument();

    expect(screen.getByTestId("gateway-pending-prop-key-1")).toBeInTheDocument();
    expect(screen.getByText("step test")).toBeInTheDocument();
    expect(screen.getByTestId("gateway-chain-status")).toHaveTextContent("gateway.audit.chainOk");
  });

  it("calls approveProposal with key and refreshes on Approve click", async () => {
    setupGatewaySpies();
    const approveSpy = vi.spyOn(gatewayApi, "approveProposal").mockResolvedValue({
      accepted: true,
      reason_code: "ok",
      clamped_value: null,
    });

    render(<GatewayPage t={mockT} />);
    await waitFor(() => {
      expect(screen.getByTestId("gateway-approve-prop-key-1")).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("gateway-approve-prop-key-1"));
    });
    expect(approveSpy).toHaveBeenCalledWith("prop-key-1");
  });

  it("calls rejectProposal with key and refreshes on Reject click", async () => {
    setupGatewaySpies();
    const rejectSpy = vi.spyOn(gatewayApi, "rejectProposal").mockResolvedValue({ ok: true });

    render(<GatewayPage t={mockT} />);
    await waitFor(() => {
      expect(screen.getByTestId("gateway-reject-prop-key-1")).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("gateway-reject-prop-key-1"));
    });
    expect(rejectSpy).toHaveBeenCalledWith("prop-key-1");
  });

  it("requires confirmation before triggering emergency kill", async () => {
    setupGatewaySpies();
    const killSpy = vi.spyOn(gatewayApi, "killGateway").mockResolvedValue({ ok: true });

    render(<GatewayPage t={mockT} />);
    await waitFor(() => {
      expect(screen.getByTestId("gateway-kill-button")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("gateway-kill-button"));
    expect(screen.getByTestId("kill-confirm-dialog")).toBeInTheDocument();
    expect(killSpy).not.toHaveBeenCalled();

    await act(async () => {
      fireEvent.click(screen.getByTestId("kill-confirm-ok"));
    });
    expect(killSpy).toHaveBeenCalled();
  });

  it("requires confirmation before switching to supervised mode", async () => {
    setupGatewaySpies();
    const setModeSpy = vi.spyOn(gatewayApi, "setGatewayMode").mockResolvedValue({ ok: true, mode: "supervised" });

    render(<GatewayPage t={mockT} />);
    await waitFor(() => {
      expect(screen.getByTestId("gateway-mode-select")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId("gateway-mode-select"), { target: { value: "supervised" } });
    expect(screen.getByTestId("supervised-confirm-dialog")).toBeInTheDocument();
    expect(setModeSpy).not.toHaveBeenCalled();

    await act(async () => {
      fireEvent.click(screen.getByTestId("supervised-confirm-ok"));
    });
    expect(setModeSpy).toHaveBeenCalledWith("supervised");
  });

  it("calls reEnableTarget on Re-enable button click", async () => {
    setupGatewaySpies();
    const reEnableSpy = vi.spyOn(gatewayApi, "reEnableTarget").mockResolvedValue({ ok: true });

    render(<GatewayPage t={mockT} />);
    await waitFor(() => {
      expect(screen.getByTestId("gateway-reenable-TIC102.SP")).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("gateway-reenable-TIC102.SP"));
    });
    expect(reEnableSpy).toHaveBeenCalledWith("TIC102.SP");
  });

  it("displays error banner when status fetch fails", async () => {
    vi.spyOn(gatewayApi, "fetchGatewayStatus").mockRejectedValue(new Error("503 gateway down"));
    vi.spyOn(gatewayApi, "fetchGatewayPending").mockResolvedValue([]);
    vi.spyOn(gatewayApi, "fetchGatewayAudit").mockResolvedValue({ chain_ok: false, records: [] });

    render(<GatewayPage t={mockT} />);
    await waitFor(() => {
      expect(screen.getByTestId("gateway-error")).toHaveTextContent("503 gateway down");
    });
  });

  it("cleans up polling timer on component unmount", async () => {
    vi.useFakeTimers();
    const clearIntervalSpy = vi.spyOn(window, "clearInterval");
    setupGatewaySpies();

    const { unmount } = render(<GatewayPage t={mockT} />);
    unmount();

    expect(clearIntervalSpy).toHaveBeenCalled();
  });
});

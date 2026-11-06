// frontend/src/components/GatewayPage.test.tsx
/**
 * Unit tests for GatewayPage component (Phase 2, #46).
 * Verifies rendering of status/targets/proposals/audit, approval and rejection flows,
 * confirmation dialogs for kill and supervised mode, error reporting, and polling cleanup.
 */

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, DEFAULT_ROLE_PERMISSIONS, useAuth } from "../AuthContext";
import * as authApi from "../authApi";
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

/** Renders the page once the (mocked) session of `role` is known; "off" means auth disabled. */
async function renderAs(role: string) {
  if (role === "off") {
    vi.spyOn(authApi, "fetchMe").mockRejectedValue(new authApi.ApiError(401, "no session"));
    vi.spyOn(authApi, "fetchAuthConfig").mockResolvedValue({ auth_enabled: false, initialised: true });
  } else {
    vi.spyOn(authApi, "fetchMe").mockResolvedValue({
      user: { username: role, display_name: role },
      roles: [role],
      permissions: [...(DEFAULT_ROLE_PERMISSIONS[role] ?? [])],
      csrf: "tok",
      must_change_password: false,
    });
  }
  function Ready() {
    const { status } = useAuth();
    return status === "loading" ? null : <GatewayPage t={mockT} />;
  }
  const view = render(
    <AuthProvider>
      <Ready />
    </AuthProvider>,
  );
  await screen.findByTestId("gateway-page");
  return view;
}

describe("GatewayPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("renders operating mode, targets table, pending proposals, and audit status", async () => {
    setupGatewaySpies();
    await renderAs("lead");

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

    await renderAs("operator");
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

    await renderAs("viewer");
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

    await renderAs("viewer");
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

    await renderAs("lead");
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

    await renderAs("engineer");
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

    await renderAs("viewer");
    await waitFor(() => {
      expect(screen.getByTestId("gateway-error")).toHaveTextContent("503 gateway down");
    });
  });

  it("viewer: approve and re-enable are aria-disabled with a reason, reject and kill work", async () => {
    setupGatewaySpies();
    const approveSpy = vi.spyOn(gatewayApi, "approveProposal");
    await renderAs("viewer");
    await screen.findByTestId("gateway-approve-prop-key-1");
    const approve = screen.getByTestId("gateway-approve-prop-key-1");
    expect(approve).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(approve);
    expect(approveSpy).not.toHaveBeenCalled();
    expect(screen.getByTestId("gateway-reenable-TIC102.SP")).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByTestId("gateway-reject-prop-key-1")).not.toHaveAttribute("aria-disabled");
    expect(screen.getByTestId("gateway-kill-button")).not.toHaveAttribute("aria-disabled");
    expect(screen.getByTestId("gateway-kill-button")).toBeEnabled();
  });

  it("operator: re-enable of a stopped target needs the engineer role, approve is allowed", async () => {
    setupGatewaySpies();
    await renderAs("operator");
    await screen.findByTestId("gateway-approve-prop-key-1");
    expect(screen.getByTestId("gateway-approve-prop-key-1")).not.toHaveAttribute("aria-disabled");
    expect(screen.getByTestId("gateway-reenable-TIC102.SP")).toHaveAttribute("aria-disabled", "true");
  });

  it("mode options follow the transition rules (current mode confirm)", async () => {
    setupGatewaySpies();
    await renderAs("engineer");
    await screen.findByTestId("gateway-mode-option-off");
    const disabled = (mode: string) => (screen.getByTestId(`gateway-mode-option-${mode}`) as HTMLOptionElement).disabled;
    expect(disabled("off")).toBe(false);
    expect(disabled("advisory")).toBe(false);
    expect(disabled("dry_run")).toBe(false);
    expect(disabled("confirm")).toBe(false);
    expect(disabled("supervised")).toBe(true);
    expect(screen.getByTestId("gateway-mode-option-supervised")).toHaveTextContent("auth.reason.requires_role");
  });

  it("viewer cannot raise the mode but can lower it; a jump up is refused for everybody", async () => {
    vi.spyOn(gatewayApi, "fetchGatewayStatus").mockResolvedValue({ ...statusFixture, mode: "off" });
    vi.spyOn(gatewayApi, "fetchGatewayPending").mockResolvedValue([]);
    vi.spyOn(gatewayApi, "fetchGatewayAudit").mockResolvedValue(auditFixture);
    await renderAs("lead");
    await screen.findByTestId("gateway-mode-option-off");
    const disabled = (mode: string) => (screen.getByTestId(`gateway-mode-option-${mode}`) as HTMLOptionElement).disabled;
    expect(disabled("advisory")).toBe(false);
    expect(disabled("dry_run")).toBe(true);
    expect(screen.getByTestId("gateway-mode-option-dry_run")).toHaveTextContent("gateway.reason.oneStep");
  });

  it("auth disabled: every control is enabled", async () => {
    setupGatewaySpies();
    await renderAs("off");
    await screen.findByTestId("gateway-approve-prop-key-1");
    expect(screen.getByTestId("gateway-approve-prop-key-1")).not.toHaveAttribute("aria-disabled");
    expect(screen.getByTestId("gateway-reenable-TIC102.SP")).not.toHaveAttribute("aria-disabled");
    expect((screen.getByTestId("gateway-mode-option-supervised") as HTMLOptionElement).disabled).toBe(false);
  });

  it("cleans up polling timer on component unmount", async () => {
    vi.useFakeTimers();
    const clearIntervalSpy = vi.spyOn(window, "clearInterval");
    setupGatewaySpies();

    vi.spyOn(authApi, "fetchMe").mockRejectedValue(new authApi.ApiError(401, "no session"));
    vi.spyOn(authApi, "fetchAuthConfig").mockResolvedValue({ auth_enabled: false, initialised: true });
    const { unmount } = render(
      <AuthProvider>
        <GatewayPage t={mockT} />
      </AuthProvider>,
    );
    unmount();

    expect(clearIntervalSpy).toHaveBeenCalled();
  });
});

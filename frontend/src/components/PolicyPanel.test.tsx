// frontend/src/components/PolicyPanel.test.tsx
/**
 * Component tests for PolicyPanel loading, roles, diff and accessibility (ADR 013, #46/#47):
 * what each role gets to see, which requests are made, how load errors are shown, the diff text,
 * the number inputs and the a11y wiring. Actions (save/pin/reload) are in PolicyPanelActions.test.tsx.
 */

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../AuthContext";
import * as policyApi from "../policyApi";
import { PolicyError } from "../policyApi";
import { PolicyPanel } from "../PolicyPanel";
import type { PolicyDocument } from "../policyModel";
import { DRAFT, LIVE, LIVE_DOC, TARGET, mockAuthSession, renderPanel, setupPolicySpies, t } from "../policyTestKit";

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("PolicyPanel - live policy", () => {
  it("shows the canonical digest as the policy digest and pin.digest only as the file digest", async () => {
    setupPolicySpies();
    await renderPanel("lead");
    expect(screen.getByTestId("live-digest")).toHaveTextContent("live_digest_111");
    expect(screen.getByTestId("live-digest")).not.toHaveTextContent("file_digest_aaa");
    expect(screen.getByTestId("live-file-digest")).toHaveTextContent("File digest: file_digest_aaa");
    expect(screen.getByTestId("live-mode-cap")).toHaveTextContent("advisory");
    expect(screen.getByTestId("live-extra-properties")).toHaveTextContent("Plant-A");
    expect(screen.getByTestId("live-target-FIC101.SP")).toBeInTheDocument();
  });

  it("prefers the server's file_digest over pin.digest when present", async () => {
    setupPolicySpies({ ...LIVE, file_digest: "filebytes_999" });
    await renderPanel("lead");
    expect(screen.getByTestId("live-file-digest")).toHaveTextContent("filebytes_999");
  });

  it("handles a null live policy", async () => {
    setupPolicySpies({ document: null, pin: null, mode_cap: null, digest: null }, null);
    await renderPanel("lead");
    expect(screen.getByTestId("live-policy-empty")).toBeInTheDocument();
  });
});

describe("PolicyPanel - who loads the draft", () => {
  it.each(["viewer", "operator", "admin"])("%s sees the live policy and never requests the draft", async (role) => {
    const { fetchDraft } = setupPolicySpies();
    fetchDraft.mockRejectedValue(new PolicyError(403, "forbidden"));
    await renderPanel(role);
    expect(screen.getByTestId("live-policy-card")).toBeInTheDocument();
    expect(fetchDraft).not.toHaveBeenCalled();
    expect(screen.queryByTestId("draft-editor-section")).not.toBeInTheDocument();
    expect(screen.queryByTestId("diff-view-section")).not.toBeInTheDocument();
    expect(screen.queryByTestId("policy-server-error")).not.toBeInTheDocument();
  });

  it("an engineer whose draft read is refused (403) keeps the live card and sees the error", async () => {
    const { fetchDraft } = setupPolicySpies();
    fetchDraft.mockRejectedValue(new PolicyError(403, "policy.edit required"));
    await renderPanel("engineer");
    expect(screen.getByTestId("live-policy-card")).toBeInTheDocument();
    expect(screen.getByTestId("policy-server-error")).toHaveTextContent("Not permitted: policy.edit required");
    expect(screen.queryByTestId("draft-editor-section")).not.toBeInTheDocument();
  });

  it("a network failure while reading the draft becomes an error, not an unhandled rejection", async () => {
    const { fetchDraft } = setupPolicySpies();
    fetchDraft.mockRejectedValue(new TypeError("Failed to fetch"));
    await renderPanel("engineer");
    expect(screen.getByTestId("policy-server-error")).toHaveTextContent("Failed to fetch");
    expect(screen.getByTestId("live-policy-card")).toBeInTheDocument();
  });

  it("a failed live read shows the error and not the misleading 'nothing pinned' banner", async () => {
    const { fetchLive } = setupPolicySpies();
    fetchLive.mockRejectedValue(new PolicyError(504, "Gateway Timeout"));
    await renderPanel("engineer");
    expect(screen.getByTestId("policy-server-error")).toHaveTextContent("did not answer in time");
    expect(screen.queryByTestId("live-policy-empty")).not.toBeInTheDocument();
    expect(screen.queryByTestId("draft-editor-section")).not.toBeInTheDocument();
  });

  it("an engineer without a server draft starts from the live policy and is told so", async () => {
    setupPolicySpies(LIVE, null);
    await renderPanel("engineer");
    expect(screen.getByTestId("draft-no-server")).toBeInTheDocument();
    expect(screen.getByTestId("target-editor-row-FIC101.SP")).toBeInTheDocument();
    expect(screen.getByTestId("diff-no-server-draft")).toBeInTheDocument();
  });
});

describe("PolicyPanel - diff of what would be pinned", () => {
  it("interpolates the explanation text and badges loosening", async () => {
    setupPolicySpies();
    await renderPanel("lead");
    const container = screen.getByTestId("policy-diff-container");
    expect(container).toHaveTextContent("Max step increased from 2 to 5");
    expect(container).toHaveTextContent("Global mode raised from advisory to confirm");
    expect(container.textContent).not.toMatch(/\{\w+\}/);
    expect(screen.getAllByTestId("badge-loosening")[0]).toHaveTextContent("[LOOSENING]");
    expect(screen.getByTestId("risk-summary-counts")).toHaveTextContent("2 loosening, 0 tightening");
  });

  it("renders changed extra properties", async () => {
    setupPolicySpies();
    await renderPanel("lead");
    expect(screen.getByTestId("diff-extra-custom_facility")).toHaveTextContent("custom_facility");
    expect(screen.getByTestId("diff-extra-custom_facility")).toHaveTextContent("Plant-A");
  });

  it("marks an added target as loosening and a removed one as tightening", async () => {
    const draftDoc: PolicyDocument = { ...LIVE_DOC, targets: { "NEW.SP": { ...TARGET } } };
    setupPolicySpies(LIVE, { ...DRAFT, document: draftDoc });
    await renderPanel("lead");
    expect(screen.getByTestId("diff-target-NEW.SP")).toHaveTextContent("Target NEW.SP (added)");
    expect(screen.getByTestId("diff-target-NEW.SP").querySelector("[data-testid=badge-loosening]")).not.toBeNull();
    expect(screen.getByTestId("diff-target-FIC101.SP")).toHaveTextContent("Target FIC101.SP (removed)");
    expect(screen.getByTestId("diff-target-FIC101.SP").querySelector("[data-testid=badge-tightening]")).not.toBeNull();
  });

  it("flags a draft mode change when no live policy exists", async () => {
    setupPolicySpies({ document: null, pin: null, mode_cap: null, digest: null }, DRAFT);
    await renderPanel("lead");
    expect(screen.getByTestId("diff-mode-change")).toHaveTextContent("off");
    expect(screen.getByTestId("diff-mode-change")).toHaveTextContent("confirm");
    expect(screen.getByTestId("diff-mode-change").querySelector("[data-testid=badge-loosening]")).not.toBeNull();
  });

  it("says so when live and draft are identical", async () => {
    setupPolicySpies(LIVE, { ...DRAFT, document: LIVE_DOC });
    await renderPanel("lead");
    expect(screen.getByTestId("policy-diff-no-changes")).toBeInTheDocument();
  });
});

describe("PolicyPanel - number inputs", () => {
  beforeEach(() => {
    setupPolicySpies();
  });

  it("keeps a cleared field empty and invalid (never 0) and disables Save with the reason", async () => {
    await renderPanel("engineer");
    const step = screen.getByLabelText("Max step FIC101.SP") as HTMLInputElement;
    fireEvent.change(step, { target: { value: "" } });
    expect(step.value).toBe("");
    expect(step).toHaveAttribute("aria-invalid", "true");
    const save = screen.getByTestId("policy-save-button");
    expect(save).toHaveAttribute("aria-disabled", "true");
    expect(save.getAttribute("title")).toContain("Fix the invalid fields");
    expect(screen.getByTestId("policy-validation-summary")).toHaveTextContent("1 field(s) are invalid");
  });

  it("accepts exponent notation", async () => {
    await renderPanel("engineer");
    const step = screen.getByLabelText("Max step FIC101.SP") as HTMLInputElement;
    fireEvent.change(step, { target: { value: "1e3" } });
    expect(step).not.toHaveAttribute("aria-invalid", "true");
    expect(screen.getByTestId("policy-save-button")).not.toHaveAttribute("aria-disabled", "true");
  });

  it("rejects zero for a strictly positive field and negative zero as zero", async () => {
    await renderPanel("engineer");
    const step = screen.getByLabelText("Max step FIC101.SP") as HTMLInputElement;
    fireEvent.change(step, { target: { value: "-0" } });
    expect(step).toHaveAttribute("aria-invalid", "true");
    const errId = step.getAttribute("aria-describedby") ?? "";
    expect(document.getElementById(errId)).toHaveTextContent("Must be greater than 0.");
  });

  it("treats non-numeric text as empty", async () => {
    await renderPanel("engineer");
    const tol = screen.getByLabelText("Readback tolerance FIC101.SP") as HTMLInputElement;
    fireEvent.change(tol, { target: { value: "abc" } });
    expect(tol.value).toBe("");
    expect(tol).toHaveAttribute("aria-invalid", "true");
  });
});

describe("PolicyPanel - accessibility and wording", () => {
  beforeEach(() => {
    setupPolicySpies();
  });

  it("labels every control with its target tag", async () => {
    await renderPanel("engineer");
    for (const label of [
      "Min limit FIC101.SP", "Max limit FIC101.SP", "Max step FIC101.SP", "Max rate (units/s) FIC101.SP",
      "Min interval (s) FIC101.SP", "Hold-off (s) FIC101.SP", "Watchdog (s) FIC101.SP",
      "Readback tolerance FIC101.SP", "Remove Target FIC101.SP", "Allowed loop modes FIC101.SP",
    ]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
  });

  it("links limits and loop-mode errors to their controls and uses role=alert only for the summary", async () => {
    await renderPanel("engineer");
    fireEvent.change(screen.getByLabelText("Min limit FIC101.SP"), { target: { value: "500" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "CAS" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "AUTO" }));

    const low = screen.getByLabelText("Min limit FIC101.SP");
    const high = screen.getByLabelText("Max limit FIC101.SP");
    const limitsErr = document.getElementById(low.getAttribute("aria-describedby") ?? "");
    expect(limitsErr).toHaveTextContent("Low limit must be less than or equal to high limit.");
    expect(high.getAttribute("aria-describedby")).toBe(low.getAttribute("aria-describedby"));

    const group = screen.getByRole("group", { name: "Allowed loop modes FIC101.SP" });
    const modesErr = document.getElementById(group.getAttribute("aria-describedby") ?? "");
    expect(modesErr).toHaveTextContent("At least one loop mode must be selected.");

    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0]).toBe(screen.getByTestId("policy-validation-summary"));
  });

  it("has no hardcoded English: every visible word and label goes through t()", async () => {
    const keyOnly = (key: string) => `<${key}>`;
    await renderPanel("lead", { translateFn: keyOnly, gatewayMode: "confirm" });
    const labelled = Array.from(document.querySelectorAll("[aria-label],[title]"))
      .map((el) => `${el.getAttribute("aria-label") ?? ""} ${el.getAttribute("title") ?? ""}`);
    const text = `${document.body.textContent ?? ""} ${labelled.join(" ")}`;
    expect(text).not.toMatch(/units\/s|Busy|\bTarget\b|\bMode\b|loosening,|tightening\b(?!>)|\(added\)|\(removed\)/);
    expect(text).toContain("<policy.diff.target>");
  });

  it("shows the zero-targets warning for an empty draft", async () => {
    setupPolicySpies(LIVE, { ...DRAFT, document: { version: 1, mode: "off", targets: {} } });
    await renderPanel("engineer");
    expect(screen.getByTestId("zero-targets-warning")).toHaveTextContent("0 targets");
  });

  it("renders 100 targets", async () => {
    const targets: PolicyDocument["targets"] = {};
    for (let i = 0; i < 100; i++) targets[`TAG_${String(i).padStart(3, "0")}`] = { ...TARGET };
    setupPolicySpies(LIVE, { ...DRAFT, document: { version: 1, mode: "off", targets } });
    await renderPanel("engineer");
    expect(screen.getByTestId("target-editor-row-TAG_000")).toBeInTheDocument();
    expect(screen.getByTestId("target-editor-row-TAG_099")).toBeInTheDocument();
  });
});

describe("PolicyPanel - lifecycle", () => {
  it("a live read that resolves after unmount triggers no draft request and no console error", async () => {
    mockAuthSession("lead", "lead1");
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    const warns = vi.spyOn(console, "warn").mockImplementation(() => {});
    let resolveLive: (v: policyApi.LivePolicyResponse) => void = () => {};
    const { fetchDraft } = setupPolicySpies();
    vi.spyOn(policyApi, "fetchLivePolicy").mockReturnValue(new Promise((res) => { resolveLive = res; }));

    const { unmount } = render(
      <AuthProvider t={t}>
        <PolicyPanel gatewayMode="advisory" t={t} />
      </AuthProvider>,
    );
    await waitFor(() => expect(policyApi.fetchLivePolicy).toHaveBeenCalled());
    unmount();
    await act(async () => {
      resolveLive(LIVE);
      await Promise.resolve();
    });
    expect(fetchDraft).not.toHaveBeenCalled();
    expect(errors).not.toHaveBeenCalled();
    expect(warns).not.toHaveBeenCalled();
  });

  it("a draft that resolves after unmount causes no state update or console error", async () => {
    mockAuthSession("engineer", "eng1");
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    let resolveDraft: (v: policyApi.DraftPolicyResponse) => void = () => {};
    const { fetchDraft } = setupPolicySpies();
    fetchDraft.mockReturnValue(new Promise((res) => { resolveDraft = res; }));

    const { unmount } = render(
      <AuthProvider t={t}>
        <PolicyPanel gatewayMode="advisory" t={t} />
      </AuthProvider>,
    );
    await waitFor(() => expect(fetchDraft).toHaveBeenCalledTimes(1));
    unmount();
    await act(async () => {
      resolveDraft(DRAFT);
      await Promise.resolve();
    });
    expect(screen.queryByTestId("policy-panel")).not.toBeInTheDocument();
    expect(errors).not.toHaveBeenCalled();
  });
});

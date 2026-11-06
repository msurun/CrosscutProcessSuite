// frontend/src/components/PolicyPanelActions.test.tsx
/**
 * Component tests for the PolicyPanel actions (ADR 013, #46/#47): Save with refetch, Pin gating
 * (unsaved edits, two-person rule with the server's name normalisation, local-dev, review tick),
 * Pin double click, Reload by gateway mode, and the message for each server error variant.
 */

import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as policyApi from "../policyApi";
import { PolicyError } from "../policyApi";
import { DRAFT, DRAFT_DOC, isDisabled, reasonOf, renderPanel, setupPolicySpies } from "../policyTestKit";

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

const click = async (testId: string) => {
  await act(async () => {
    fireEvent.click(screen.getByTestId(testId));
  });
};

const editMaxStep = (value: string) =>
  fireEvent.change(screen.getByLabelText("Max step FIC101.SP"), { target: { value } });

describe("PolicyPanel - Save", () => {
  it("saves, refetches the draft and shows the server's author and digest", async () => {
    const { fetchDraft } = setupPolicySpies();
    const save = vi.spyOn(policyApi, "saveDraftPolicy").mockResolvedValue({ ok: true, digest: "saved_333" });
    await renderPanel("engineer", { username: "engineer_user" });
    editMaxStep("7");
    const savedDoc = { ...DRAFT_DOC, targets: { "FIC101.SP": { ...DRAFT_DOC.targets["FIC101.SP"], max_step: 7 } } };
    fetchDraft.mockResolvedValue({ ...DRAFT, document: savedDoc, author: "engineer_user", digest: "saved_333" });

    await click("policy-save-button");

    expect(save).toHaveBeenCalledTimes(1);
    expect(save.mock.calls[0][0].targets["FIC101.SP"].max_step).toBe(7);
    await waitFor(() => expect(screen.getByTestId("policy-server-notice")).toHaveTextContent("Draft successfully saved"));
    expect(fetchDraft).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("draft-digest")).toHaveTextContent("saved_333");
    expect(screen.getByTestId("draft-author")).toHaveTextContent("engineer_user");
    expect(screen.queryByTestId("unsaved-diff-section")).not.toBeInTheDocument();
  });

  it("an engineer cannot pin: the button names the missing role", async () => {
    setupPolicySpies();
    await renderPanel("engineer");
    const pin = screen.getByTestId("policy-pin-button");
    expect(isDisabled(pin)).toBe(true);
    expect(reasonOf(pin).toLowerCase()).toContain("lead");
  });

  it.each([
    [new PolicyError(422, "<b>Invalid</b> <script>alert(1)</script>"), "<b>Invalid</b> <script>alert(1)</script>"],
  ])("shows a 422 verbatim as plain text and creates no element from it", async (err, text) => {
    setupPolicySpies();
    vi.spyOn(policyApi, "saveDraftPolicy").mockRejectedValue(err);
    const { container } = await renderPanel("engineer");
    await click("policy-save-button");
    const banner = await screen.findByTestId("policy-server-error");
    expect(banner).toHaveTextContent(text);
    expect(banner.textContent).toContain("<script>alert(1)</script>");
    expect(container.querySelector("b")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
  });

  it("a second click while Save is in flight sends no second request", async () => {
    setupPolicySpies();
    let resolveSave: (v: { ok: boolean; digest: string }) => void = () => {};
    const save = vi.spyOn(policyApi, "saveDraftPolicy").mockReturnValue(new Promise((res) => { resolveSave = res; }));
    await renderPanel("engineer");
    await act(async () => {
      fireEvent.click(screen.getByTestId("policy-save-button"));
      fireEvent.click(screen.getByTestId("policy-save-button"));
    });
    expect(save).toHaveBeenCalledTimes(1);
    expect(reasonOf(screen.getByTestId("policy-save-button"))).toContain("in progress");
    await act(async () => resolveSave({ ok: true, digest: DRAFT.digest }));
  });
});

describe("PolicyPanel - Pin gating", () => {
  beforeEach(() => {
    setupPolicySpies();
  });

  it("is disabled while the local document differs from the server draft, and the unsaved diff is separate", async () => {
    await renderPanel("lead", { username: "lead_different_person" });
    fireEvent.click(screen.getByTestId("policy-review-checkbox"));
    expect(isDisabled(screen.getByTestId("policy-pin-button"))).toBe(false);

    editMaxStep("9");

    const pin = screen.getByTestId("policy-pin-button");
    expect(isDisabled(pin)).toBe(true);
    expect(reasonOf(pin)).toContain("unsaved edits");
    expect(screen.getByTestId("unsaved-diff-section")).toHaveTextContent("from 5 to 9");
    expect(screen.getByTestId("diff-view-section")).toHaveTextContent("from 2 to 5");
    expect(screen.getByTestId("diff-view-section")).not.toHaveTextContent("to 9");

    await click("policy-discard-button");
    expect(screen.queryByTestId("unsaved-diff-section")).not.toBeInTheDocument();
  });

  it("is disabled with a reason when there is no saved draft", async () => {
    setupPolicySpies(undefined, null);
    await renderPanel("lead", { username: "lead_different_person" });
    const pin = screen.getByTestId("policy-pin-button");
    expect(isDisabled(pin)).toBe(true);
    expect(reasonOf(pin)).toContain("no saved draft");
  });

  it("applies the server's name normalisation to the two-person rule", async () => {
    await renderPanel("lead", { username: "  ENGINEER_Author " });
    fireEvent.click(screen.getByTestId("policy-review-checkbox"));
    const pin = screen.getByTestId("policy-pin-button");
    expect(isDisabled(pin)).toBe(true);
    expect(reasonOf(pin)).toContain("Two-person rule");
  });

  it("with auth disabled the actor is local-dev: a local-dev draft cannot be pinned", async () => {
    setupPolicySpies(undefined, { ...DRAFT, author: "local-dev" });
    await renderPanel("off");
    fireEvent.click(screen.getByTestId("policy-review-checkbox"));
    const pin = screen.getByTestId("policy-pin-button");
    expect(isDisabled(pin)).toBe(true);
    expect(reasonOf(pin)).toContain("local-dev");
  });

  it("with auth disabled a draft by someone else can be pinned once reviewed", async () => {
    await renderPanel("off");
    expect(isDisabled(screen.getByTestId("policy-pin-button"))).toBe(true);
    fireEvent.click(screen.getByTestId("policy-review-checkbox"));
    expect(isDisabled(screen.getByTestId("policy-pin-button"))).toBe(false);
  });

  it("pins the loaded draft's digest after review, and a double click sends one request", async () => {
    let resolvePin: (v: { ok: boolean }) => void = () => {};
    const pin = vi.spyOn(policyApi, "pinPolicy").mockReturnValue(new Promise((res) => { resolvePin = res; }));
    await renderPanel("lead", { username: "lead_different_person" });
    expect(isDisabled(screen.getByTestId("policy-pin-button"))).toBe(true);
    fireEvent.click(screen.getByTestId("policy-review-checkbox"));
    await act(async () => {
      fireEvent.click(screen.getByTestId("policy-pin-button"));
      fireEvent.click(screen.getByTestId("policy-pin-button"));
    });
    expect(pin).toHaveBeenCalledTimes(1);
    expect(pin).toHaveBeenCalledWith("draft_digest_222");
    await act(async () => resolvePin({ ok: true }));
    await waitFor(() => expect(screen.getByTestId("policy-server-notice")).toHaveTextContent("Policy successfully pinned"));
  });

  it("unticks the review after a 409 reload that brings a new draft", async () => {
    const { fetchDraft } = setupPolicySpies();
    vi.spyOn(policyApi, "pinPolicy").mockRejectedValue(new PolicyError(409, "draft_changed"));
    await renderPanel("lead", { username: "lead_different_person" });
    fireEvent.click(screen.getByTestId("policy-review-checkbox"));
    fetchDraft.mockResolvedValue({ ...DRAFT, digest: "draft_digest_333" });

    await click("policy-pin-button");

    await waitFor(() => expect(screen.getByTestId("policy-server-error")).toHaveTextContent("server draft changed"));
    expect(fetchDraft).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("policy-review-checkbox")).not.toBeChecked();
    expect(screen.getByTestId("draft-digest")).toHaveTextContent("draft_digest_333");
    expect(isDisabled(screen.getByTestId("policy-pin-button"))).toBe(true);
  });

  it("unticks the review even when the reloaded draft is unchanged", async () => {
    vi.spyOn(policyApi, "pinPolicy").mockRejectedValue(new PolicyError(409, "draft_changed"));
    await renderPanel("lead", { username: "lead_different_person" });
    fireEvent.click(screen.getByTestId("policy-review-checkbox"));
    await click("policy-pin-button");
    await waitFor(() => expect(screen.getByTestId("policy-server-error")).toBeInTheDocument());
    expect(screen.getByTestId("policy-review-checkbox")).not.toBeChecked();
  });
});

describe("PolicyPanel - server error variants on Pin", () => {
  const cases: Array<[number, string, string]> = [
    [409, "no_draft", "no draft on the server"],
    [409, "draft_bad_signature", "signature is not valid"],
    [409, "key_missing", "signing key"],
    [409, "key_unreadable", "signing key"],
    [409, "policy_path_not_configured", "no policy file path"],
    [409, "something_new", "something_new"],
    [403, "two_person_rule", "Not permitted: two_person_rule"],
    [504, "Gateway Timeout", "did not answer in time"],
    [428, "step_up_required", "Step-up verification was cancelled"],
    [500, "boom", "Policy error: boom"],
  ];

  it.each(cases)("%i %s", async (status, detail, expected) => {
    setupPolicySpies();
    vi.spyOn(policyApi, "pinPolicy").mockRejectedValue(new PolicyError(status, detail));
    await renderPanel("lead", { username: "lead_different_person" });
    fireEvent.click(screen.getByTestId("policy-review-checkbox"));
    await click("policy-pin-button");
    await waitFor(() => expect(screen.getByTestId("policy-server-error")).toHaveTextContent(expected));
    expect(screen.getByTestId("policy-save-button")).toBeInTheDocument();
  });
});

describe("PolicyPanel - Reload", () => {
  beforeEach(() => {
    setupPolicySpies();
  });

  it.each(["confirm", "dry_run", "supervised"])("is disabled in gateway mode %s with the reason", async (mode) => {
    await renderPanel("lead", { gatewayMode: mode });
    const reload = screen.getByTestId("policy-reload-button");
    expect(isDisabled(reload)).toBe(true);
    expect(reasonOf(reload)).toContain("off or advisory");
  });

  it("is disabled when the gateway mode is unknown", async () => {
    await renderPanel("lead", { gatewayMode: "unknown" });
    const reload = screen.getByTestId("policy-reload-button");
    expect(isDisabled(reload)).toBe(true);
    expect(reasonOf(reload)).toContain("unknown");
  });

  it("reloads in advisory mode and then refreshes the policy", async () => {
    const reload = vi.spyOn(policyApi, "reloadPolicy").mockResolvedValue({ ok: true });
    await renderPanel("lead", { gatewayMode: "advisory" });
    expect(isDisabled(screen.getByTestId("policy-reload-button"))).toBe(false);
    await click("policy-reload-button");
    expect(reload).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(policyApi.fetchLivePolicy).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId("policy-server-notice")).toHaveTextContent("successfully reloaded");
  });

  it("shows the server's refusal when the gateway mode changed in the meantime (409)", async () => {
    vi.spyOn(policyApi, "reloadPolicy").mockRejectedValue(new PolicyError(409, "mode_not_reloadable"));
    await renderPanel("lead", { gatewayMode: "off" });
    await click("policy-reload-button");
    await waitFor(() => expect(screen.getByTestId("policy-server-error")).toHaveTextContent("mode_not_reloadable"));
  });

  it("an engineer cannot reload", async () => {
    await renderPanel("engineer", { gatewayMode: "off" });
    expect(isDisabled(screen.getByTestId("policy-reload-button"))).toBe(true);
  });

  it("changing the global mode marks the draft as edited", async () => {
    await renderPanel("engineer");
    fireEvent.change(screen.getByTestId("policy-mode-select"), { target: { value: "off" } });
    expect(screen.getByTestId("unsaved-diff-section")).toBeInTheDocument();
  });
});

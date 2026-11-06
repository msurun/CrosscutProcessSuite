// frontend/src/components/StepUpDialog.test.tsx
/**
 * Unit tests for StepUpDialog: accessibility, error mapping, pending state,
 * password confidentiality and focus handling.
 */

import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../authApi";
import { StepUpDialog } from "./StepUpDialog";

type StepUpResult = Awaited<ReturnType<typeof authApi.stepUp>>;

const mockT = (key: string, params?: Record<string, string | number>) =>
  params ? `${key}:${Object.values(params).join(",")}` : key;
const OK = { ok: true, valid_for_s: 300 } as StepUpResult;
const SECRET = "s3cret-pw";
const LABEL = "auth.stepup.passwordLabel";

function TestHost() {
  const [isOpen, setIsOpen] = useState(false);
  return (
    <div>
      <button type="button" data-testid="open-trigger" onClick={() => setIsOpen(true)}>Open</button>
      <StepUpDialog isOpen={isOpen} onSuccess={() => setIsOpen(false)} onCancel={() => setIsOpen(false)} t={mockT} />
    </div>
  );
}

function renderOpen() {
  const onSuccess = vi.fn();
  const onCancel = vi.fn();
  const view = render(<StepUpDialog isOpen={true} onSuccess={onSuccess} onCancel={onCancel} t={mockT} />);
  return { ...view, onSuccess, onCancel };
}

async function submit(value = SECRET) {
  fireEvent.change(screen.getByLabelText(LABEL), { target: { value } });
  await act(async () => {
    fireEvent.click(screen.getByTestId("stepup-submit"));
  });
}

function deferred() {
  let resolve!: (v: StepUpResult) => void;
  const promise = new Promise<StepUpResult>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("StepUpDialog", () => {
  it("renders dialog semantics", () => {
    renderOpen();
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAttribute("aria-labelledby", "step-up-title");
    expect(dialog).toHaveAttribute("aria-describedby", "step-up-desc");
  });

  it("shows wrong password inline, stays open and clears the input", async () => {
    vi.spyOn(authApi, "stepUp").mockRejectedValueOnce(new authApi.ApiError(403, "wrong_password"));
    const { onCancel } = renderOpen();
    await submit();
    expect(screen.getByTestId("stepup-error")).toHaveTextContent("auth.stepup.errorWrongPassword");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText(LABEL)).toHaveValue("");
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("maps 423 with and without retry time", async () => {
    const spy = vi.spyOn(authApi, "stepUp");
    spy.mockRejectedValueOnce(new authApi.ApiError(423, "locked", 42));
    renderOpen();
    await submit();
    expect(screen.getByTestId("stepup-error")).toHaveTextContent("auth.stepup.error423:42");
    spy.mockRejectedValueOnce(new authApi.ApiError(423, "locked"));
    await submit();
    expect(screen.getByTestId("stepup-error")).toHaveTextContent(/^auth\.stepup\.error423NoTime$/);
  });

  it("maps 429, other statuses and network errors", async () => {
    const spy = vi.spyOn(authApi, "stepUp");
    renderOpen();
    spy.mockRejectedValueOnce(new authApi.ApiError(429, "rate"));
    await submit();
    expect(screen.getByTestId("stepup-error")).toHaveTextContent("auth.stepup.error429");
    spy.mockRejectedValueOnce(new authApi.ApiError(500, "boom"));
    await submit();
    expect(screen.getByTestId("stepup-error")).toHaveTextContent("auth.stepup.errorGeneric:boom");
    spy.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await submit();
    expect(screen.getByTestId("stepup-error")).toHaveTextContent("auth.stepup.errorGeneric:Failed to fetch");
  });

  it("shows 401 error and calls onCancel", async () => {
    vi.spyOn(authApi, "stepUp").mockRejectedValueOnce(new authApi.ApiError(401, "no session"));
    const { onCancel } = renderOpen();
    await submit();
    expect(screen.getByTestId("stepup-error")).toHaveTextContent("auth.stepup.error401");
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("resets error and password when reopened", async () => {
    vi.spyOn(authApi, "stepUp").mockRejectedValueOnce(new authApi.ApiError(403, "wrong_password"));
    render(<TestHost />);
    fireEvent.click(screen.getByTestId("open-trigger"));
    await submit();
    expect(screen.getByTestId("stepup-error")).toBeInTheDocument();
    fireEvent.click(screen.getByText("auth.stepup.cancelButton"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("open-trigger"));
    expect(screen.queryByTestId("stepup-error")).not.toBeInTheDocument();
    expect(screen.getByLabelText(LABEL)).toHaveValue("");
  });

  it("ignores Escape and disables Cancel while pending, honours Escape when idle", async () => {
    const d = deferred();
    vi.spyOn(authApi, "stepUp").mockReturnValueOnce(d.promise);
    const { onCancel, onSuccess } = renderOpen();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1);
    await submit();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(screen.getByText("auth.stepup.cancelButton")).toBeDisabled();
    await act(async () => d.resolve(OK));
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });

  it("calls onSuccess exactly once on success", async () => {
    vi.spyOn(authApi, "stepUp").mockResolvedValueOnce(OK);
    const { onSuccess } = renderOpen();
    await submit();
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });

  it("does not call callbacks after unmount", async () => {
    const d = deferred();
    vi.spyOn(authApi, "stepUp").mockReturnValueOnce(d.promise);
    const { onSuccess, unmount } = renderOpen();
    await submit();
    unmount();
    await act(async () => d.resolve(OK));
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("never keeps or logs the password", async () => {
    const d = deferred();
    const spy = vi.spyOn(authApi, "stepUp").mockReturnValueOnce(d.promise);
    const logs = (["log", "info", "warn", "error", "debug"] as const).map((m) => vi.spyOn(console, m));
    renderOpen();
    await submit();
    expect(spy).toHaveBeenCalledWith({ password: SECRET });
    expect(screen.getByLabelText(LABEL)).toHaveValue("");
    expect(document.body.innerHTML).not.toContain(SECRET);
    await act(async () => d.resolve(OK));
    for (const l of logs) expect(l).not.toHaveBeenCalled();
  });

  it("returns focus to the previously focused element on close", () => {
    render(<TestHost />);
    const trigger = screen.getByTestId("open-trigger");
    trigger.focus();
    fireEvent.click(trigger);
    expect(screen.getByLabelText(LABEL)).toHaveFocus();
    fireEvent.click(screen.getByText("auth.stepup.cancelButton"));
    expect(trigger).toHaveFocus();
  });

  it("traps Tab focus inside the dialog", () => {
    renderOpen();
    fireEvent.change(screen.getByLabelText(LABEL), { target: { value: "x" } });
    screen.getByTestId("stepup-submit").focus();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Tab" });
    expect(screen.getByLabelText(LABEL)).toHaveFocus();
  });
});

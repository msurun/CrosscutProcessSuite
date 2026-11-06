// frontend/src/ChangePasswordPage.test.tsx
// Tests for the forced/voluntary change-password view: client validation, API errors,
// success flow (post, refresh, onDone), clearing of fields and the sign-out button.

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChangePasswordPage } from "./ChangePasswordPage";
import { ApiError } from "./authApi";

const changePasswordMock = vi.hoisted(() => vi.fn());
const refreshMock = vi.hoisted(() => vi.fn());
const logoutMock = vi.hoisted(() => vi.fn());

vi.mock("./authApi", async () => {
  const actual = await vi.importActual<typeof import("./authApi")>("./authApi");
  return { ...actual, changePassword: changePasswordMock };
});
vi.mock("./AuthContext", () => ({
  useAuth: () => ({ refresh: refreshMock, logout: logoutMock }),
}));

const t = (key: string, params?: Record<string, string | number>) =>
  params ? `${key}|${JSON.stringify(params)}` : key;

const GOOD_OLD = "old-password-1";
const GOOD_NEW = "brand-new-pass-9";

function fill(label: string, value: string): void {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

function fillAll(oldPw: string, newPw: string, confirm: string): void {
  fill("auth.password.oldLabel", oldPw);
  fill("auth.password.newLabel", newPw);
  fill("auth.password.confirmLabel", confirm);
}

function submit(): void {
  fireEvent.click(screen.getByRole("button", { name: "auth.password.submit" }));
}

function field(label: string): HTMLInputElement {
  return screen.getByLabelText(label) as HTMLInputElement;
}

beforeEach(() => {
  changePasswordMock.mockReset();
  refreshMock.mockReset().mockResolvedValue(undefined);
  logoutMock.mockReset().mockResolvedValue(undefined);
});
afterEach(cleanup);

describe("ChangePasswordPage", () => {
  it("renders heading, notice and three password fields", () => {
    render(<ChangePasswordPage t={t} />);
    expect(screen.getByRole("heading", { name: "auth.password.title" })).toBeInTheDocument();
    expect(screen.getByText("auth.password.requiredNotice")).toBeInTheDocument();
    expect(field("auth.password.oldLabel")).toHaveAttribute("type", "password");
    expect(field("auth.password.oldLabel")).toHaveAttribute("autocomplete", "current-password");
    expect(field("auth.password.newLabel")).toHaveAttribute("autocomplete", "new-password");
    expect(field("auth.password.confirmLabel")).toHaveAttribute("type", "password");
  });

  it("blocks a too-short new password without calling the API", () => {
    render(<ChangePasswordPage t={t} />);
    fillAll(GOOD_OLD, "short", "short");
    submit();
    expect(screen.getByRole("alert")).toHaveTextContent('auth.password.tooShort|{"min":12}');
    expect(changePasswordMock).not.toHaveBeenCalled();
  });

  it("blocks a confirmation mismatch", () => {
    render(<ChangePasswordPage t={t} />);
    fillAll(GOOD_OLD, GOOD_NEW, GOOD_NEW + "x");
    submit();
    expect(screen.getByRole("alert")).toHaveTextContent("auth.password.mismatch");
    expect(changePasswordMock).not.toHaveBeenCalled();
  });

  it("blocks a new password equal to the old one", () => {
    render(<ChangePasswordPage t={t} />);
    fillAll("same-password-12", "same-password-12", "same-password-12");
    submit();
    expect(screen.getByRole("alert")).toHaveTextContent("auth.password.mustDiffer");
    expect(changePasswordMock).not.toHaveBeenCalled();
  });

  it("posts the exact body, then refreshes, then calls onDone", async () => {
    const order: string[] = [];
    changePasswordMock.mockImplementation(async () => {
      order.push("post");
      return { ok: true };
    });
    refreshMock.mockImplementation(async () => {
      order.push("refresh");
    });
    const onDone = vi.fn(() => order.push("done"));
    render(<ChangePasswordPage t={t} onDone={onDone} />);
    fillAll(GOOD_OLD, GOOD_NEW, GOOD_NEW);
    submit();
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(changePasswordMock).toHaveBeenCalledWith({ old_password: GOOD_OLD, new_password: GOOD_NEW });
    expect(order).toEqual(["post", "refresh", "done"]);
  });

  it("shows the wrong-old-password message on 403", async () => {
    changePasswordMock.mockRejectedValue(new ApiError(403, "wrong_password"));
    render(<ChangePasswordPage t={t} />);
    fillAll(GOOD_OLD, GOOD_NEW, GOOD_NEW);
    submit();
    expect(await screen.findByRole("alert")).toHaveTextContent("auth.password.wrongOld");
  });

  it("shows the server policy message on 422", async () => {
    changePasswordMock.mockRejectedValue(new ApiError(422, "new password must differ"));
    render(<ChangePasswordPage t={t} />);
    fillAll(GOOD_OLD, GOOD_NEW, GOOD_NEW);
    submit();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      'auth.password.errorServer|{"detail":"new password must differ"}',
    );
  });

  it("shows the lockout seconds on 423, and a timeless text without them", async () => {
    changePasswordMock.mockRejectedValueOnce(new ApiError(423, "locked", 42));
    render(<ChangePasswordPage t={t} />);
    fillAll(GOOD_OLD, GOOD_NEW, GOOD_NEW);
    submit();
    expect(await screen.findByRole("alert")).toHaveTextContent('auth.password.error423|{"seconds":42}');
    changePasswordMock.mockRejectedValueOnce(new ApiError(423, "locked"));
    fillAll(GOOD_OLD, GOOD_NEW, GOOD_NEW);
    submit();
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("auth.password.error423NoTime"),
    );
  });

  it("shows the rate-limit message on 429 and the session message on 401", async () => {
    changePasswordMock.mockRejectedValueOnce(new ApiError(429, "slow down"));
    render(<ChangePasswordPage t={t} />);
    fillAll(GOOD_OLD, GOOD_NEW, GOOD_NEW);
    submit();
    expect(await screen.findByRole("alert")).toHaveTextContent("auth.password.error429");
    changePasswordMock.mockRejectedValueOnce(new ApiError(401, "no session"));
    fillAll(GOOD_OLD, GOOD_NEW, GOOD_NEW);
    submit();
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("auth.password.error401"),
    );
  });

  it("clears all password fields and focuses the alert after a failure", async () => {
    changePasswordMock.mockRejectedValue(new ApiError(403, "wrong_password"));
    render(<ChangePasswordPage t={t} />);
    fillAll(GOOD_OLD, GOOD_NEW, GOOD_NEW);
    submit();
    const alert = await screen.findByRole("alert");
    expect(field("auth.password.oldLabel").value).toBe("");
    expect(field("auth.password.newLabel").value).toBe("");
    expect(field("auth.password.confirmLabel").value).toBe("");
    await waitFor(() => expect(alert).toHaveFocus());
  });

  it("falls back to the generic message for other errors", async () => {
    changePasswordMock.mockRejectedValue(new ApiError(500, "boom"));
    render(<ChangePasswordPage t={t} />);
    fillAll(GOOD_OLD, GOOD_NEW, GOOD_NEW);
    submit();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      'auth.password.errorGeneric|{"detail":"boom"}',
    );
  });

  it("signs out through the logout button", () => {
    render(<ChangePasswordPage t={t} />);
    fireEvent.click(screen.getByRole("button", { name: "auth.logout" }));
    expect(logoutMock).toHaveBeenCalledTimes(1);
  });
});

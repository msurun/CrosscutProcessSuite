// Component tests of the login page: success path, each backend error status (401/423/429/503),
// the 423 countdown driven by Retry-After, network errors, password clearing and error focus.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../authApi";
import { LoginPage } from "../LoginPage";

const loginMock = vi.fn();
vi.mock("../AuthContext", () => ({ useAuth: () => ({ login: loginMock }) }));

const t = (key: string, params?: Record<string, string | number>) =>
  params ? `${key}|${Object.values(params).join(",")}` : key;
const SESSION = {
  user: { username: "ann", display_name: "Ann" }, roles: [], permissions: [], csrf: "c",
  must_change_password: false,
};

function renderPage(onLoginSuccess = vi.fn()) {
  render(<LoginPage t={t} onLoginSuccess={onLoginSuccess} />);
  return onLoginSuccess;
}

async function submit(username = "ann", password = "secret-pass") {
  fireEvent.change(screen.getByLabelText("auth.login.usernameLabel"), { target: { value: username } });
  fireEvent.change(screen.getByLabelText("auth.login.passwordLabel"), { target: { value: password } });
  await act(async () => {
    fireEvent.click(screen.getByTestId("login-submit"));
    await vi.advanceTimersByTimeAsync(0);
  });
}

async function tick(seconds: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(seconds * 1000);
  });
}

const summary = () => screen.getByTestId("login-error-summary");
const button = () => screen.getByTestId("login-submit") as HTMLButtonElement;

beforeEach(() => {
  vi.useFakeTimers();
  loginMock.mockReset();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("LoginPage", () => {
  it("logs in with the typed credentials and calls onLoginSuccess", async () => {
    loginMock.mockResolvedValue(SESSION);
    const onSuccess = renderPage();
    await submit();
    expect(loginMock).toHaveBeenCalledWith({ username: "ann", password: "secret-pass" });
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("login-error-summary")).toBeNull();
  });

  it.each([
    [401, "auth.login.error401"],
    [429, "auth.login.error429"],
    [503, "auth.login.error503"],
  ])("shows the message for status %i", async (status, key) => {
    loginMock.mockRejectedValue(new ApiError(status, "x"));
    const onSuccess = renderPage();
    await submit();
    expect(summary()).toHaveTextContent(key);
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("counts down a 423 lockout from Retry-After and re-enables the form at 0", async () => {
    loginMock.mockRejectedValue(new ApiError(423, "locked", 3));
    renderPage();
    await submit();
    expect(summary()).toHaveTextContent("auth.login.error423|3");
    expect(button().disabled).toBe(true);
    await tick(1);
    expect(summary()).toHaveTextContent("auth.login.error423|2");
    expect(button().disabled).toBe(true);
    await tick(2);
    expect(screen.queryByTestId("login-error-summary")).toBeNull();
    expect(button().disabled).toBe(false);
  });

  it("shows the no-time message without a countdown when 423 has no Retry-After", async () => {
    loginMock.mockRejectedValue(new ApiError(423, "locked"));
    renderPage();
    await submit();
    expect(summary()).toHaveTextContent("auth.login.error423NoTime");
    await tick(5);
    expect(summary()).toHaveTextContent("auth.login.error423NoTime");
    expect(button().disabled).toBe(false);
  });

  it("shows the network message on a TypeError", async () => {
    loginMock.mockRejectedValue(new TypeError("Failed to fetch"));
    renderPage();
    await submit();
    expect(summary()).toHaveTextContent("auth.login.errorNetwork");
  });

  it("shows the generic message with the detail for other statuses", async () => {
    loginMock.mockRejectedValue(new ApiError(422, "missing fields"));
    renderPage();
    await submit();
    expect(summary()).toHaveTextContent("auth.login.errorGeneric|missing fields");
  });

  it("clears the password after a failed attempt but keeps the username", async () => {
    loginMock.mockRejectedValue(new ApiError(401, "invalid"));
    renderPage();
    await submit();
    expect((screen.getByLabelText("auth.login.passwordLabel") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("auth.login.usernameLabel") as HTMLInputElement).value).toBe("ann");
  });

  it("moves focus to the error summary after a failure", async () => {
    loginMock.mockRejectedValue(new ApiError(401, "invalid"));
    renderPage();
    await submit();
    expect(summary()).toHaveFocus();
  });
});

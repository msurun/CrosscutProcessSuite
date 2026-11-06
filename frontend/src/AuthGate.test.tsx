// frontend/src/AuthGate.test.tsx
// Tests for the gate in front of the app and for the view tabs it shows (users tab by permission).

import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, DEFAULT_ROLE_PERMISSIONS } from "./AuthContext";
import { AuthGate } from "./AuthGate";
import * as authApi from "./authApi";
import { ViewTabs } from "./components/ViewTabs";

const t = (key: string) => key;

function mockSession(role: string, mustChange = false) {
  vi.spyOn(authApi, "fetchMe").mockResolvedValue({
    user: { username: role, display_name: role },
    roles: [role],
    permissions: [...(DEFAULT_ROLE_PERMISSIONS[role] ?? [])],
    csrf: "tok",
    must_change_password: mustChange,
  });
}

function mockSignedOut(config: authApi.AuthConfig) {
  vi.spyOn(authApi, "fetchMe").mockRejectedValue(new authApi.ApiError(401, "no session"));
  vi.spyOn(authApi, "fetchAuthConfig").mockResolvedValue(config);
}

function renderGate() {
  return render(
    <AuthProvider>
      <AuthGate t={t}>
        <p>the app</p>
        <ViewTabs view="trends" onSelect={() => undefined} t={t} />
      </AuthGate>
    </AuthProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("AuthGate", () => {
  it("shows the login when signed out", async () => {
    mockSignedOut({ auth_enabled: true, initialised: true });
    renderGate();
    expect(await screen.findByText("auth.login.title")).toBeInTheDocument();
    expect(screen.queryByText("the app")).not.toBeInTheDocument();
  });

  it("shows the first-run hint when no user exists", async () => {
    mockSignedOut({ auth_enabled: true, initialised: false });
    renderGate();
    expect(await screen.findByTestId("auth-uninitialised")).toBeInTheDocument();
  });

  it("shows the app at once when auth is off, without a users tab", async () => {
    mockSignedOut({ auth_enabled: false, initialised: false });
    renderGate();
    expect(await screen.findByText("the app")).toBeInTheDocument();
    expect(screen.queryByText("nav.users")).not.toBeInTheDocument();
    expect(screen.queryByText("auth.login.title")).not.toBeInTheDocument();
  });

  it("forces the password change page", async () => {
    mockSession("operator", true);
    renderGate();
    expect(await screen.findByText("auth.password.title")).toBeInTheDocument();
    expect(screen.queryByText("the app")).not.toBeInTheDocument();
  });

  it("shows the users tab only to a user with users.manage", async () => {
    mockSession("admin");
    const first = renderGate();
    expect(await screen.findByText("nav.users")).toBeInTheDocument();
    first.unmount();
    vi.restoreAllMocks();
    mockSession("engineer");
    renderGate();
    expect(await screen.findByText("the app")).toBeInTheDocument();
    expect(screen.queryByText("nav.users")).not.toBeInTheDocument();
  });

  it("selects a view from the tabs", async () => {
    mockSession("admin");
    const onSelect = vi.fn();
    render(
      <AuthProvider>
        <AuthGate t={t}>
          <ViewTabs view="trends" onSelect={onSelect} t={t} />
        </AuthGate>
      </AuthProvider>,
    );
    fireEvent.click(await screen.findByText("nav.users"));
    expect(onSelect).toHaveBeenCalledWith("users");
  });
});

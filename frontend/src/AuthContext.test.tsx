// frontend/src/AuthContext.test.tsx
// Tests for AuthProvider, useAuth, useCan, role table drift and step-up coordination.
// authApi is mocked; subscription listeners are captured so events can be fired.

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import rolesJson from "../../schemas/auth-roles.default.json";
import {
  AuthProvider,
  DEFAULT_ROLE_PERMISSIONS,
  PERMISSION_LOWEST_ROLE,
  ROLE_ORDER,
  useAuth,
  useCan,
  type AuthContextValue,
} from "./AuthContext";
import { ApiError, type AuthSession } from "./authApi";

const listeners = vi.hoisted(() => ({
  unauthorized: new Set<() => void>(),
  passwordChange: new Set<() => void>(),
}));
const api = vi.hoisted(() => ({
  fetchMe: vi.fn(),
  fetchAuthConfig: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  stepUp: vi.fn(),
  setStepUpHandler: vi.fn(),
}));

vi.mock("./authApi", async (importActual) => {
  const actual = await importActual<typeof import("./authApi")>();
  const subscribe = (set: Set<() => void>) => (fn: () => void) => {
    set.add(fn);
    return () => set.delete(fn);
  };
  return {
    ...actual,
    ...api,
    subscribeUnauthorized: subscribe(listeners.unauthorized),
    subscribePasswordChangeRequired: subscribe(listeners.passwordChange),
  };
});

function session(over: Partial<AuthSession> = {}): AuthSession {
  return {
    user: { username: "admin", display_name: "Admin" },
    roles: ["operator"],
    permissions: ["data.view", "gw.reject"],
    csrf: "tok",
    must_change_password: false,
    stepup_valid: false,
    ...over,
  };
}

let current: AuthContextValue;

function CanRow({ permission }: { permission: string }) {
  return <li data-testid={`can-${permission}`}>{JSON.stringify(useCan(permission))}</li>;
}

function Probe({ perms }: { perms: string[] }) {
  current = useAuth();
  return (
    <ul>
      {perms.map((p) => (
        <CanRow key={p} permission={p} />
      ))}
    </ul>
  );
}

function renderAuth(perms: string[] = []) {
  return render(
    <AuthProvider>
      <Probe perms={perms} />
    </AuthProvider>,
  );
}

function canOf(p: string): { allowed: boolean; reason: string; requiredRole?: string } {
  return JSON.parse(screen.getByTestId(`can-${p}`).textContent ?? "{}");
}

beforeEach(() => {
  vi.clearAllMocks();
  api.fetchAuthConfig.mockRejectedValue(new ApiError(500, "no config"));
  listeners.unauthorized.clear();
  listeners.passwordChange.clear();
});

describe("status from /auth/config", () => {
  it("auth off -> disabled, every permission allowed", async () => {
    api.fetchMe.mockRejectedValue(new ApiError(401, "unauthorized"));
    api.fetchAuthConfig.mockResolvedValue({ auth_enabled: false, initialised: false });
    renderAuth(["users.manage", "gw.mode.up.supervised"]);
    await waitFor(() => expect(current.status).toBe("disabled"));
    expect(canOf("users.manage").allowed).toBe(true);
    expect(canOf("gw.mode.up.supervised").allowed).toBe(true);
  });

  it("auth on but no users file -> uninitialised", async () => {
    api.fetchMe.mockRejectedValue(new ApiError(401, "unauthorized"));
    api.fetchAuthConfig.mockResolvedValue({ auth_enabled: true, initialised: false });
    renderAuth();
    await waitFor(() => expect(current.status).toBe("uninitialised"));
  });

  it("auth on and initialised -> anonymous", async () => {
    api.fetchMe.mockRejectedValue(new ApiError(401, "unauthorized"));
    api.fetchAuthConfig.mockResolvedValue({ auth_enabled: true, initialised: true });
    renderAuth();
    await waitFor(() => expect(current.status).toBe("anonymous"));
  });

  it("auth off never calls /auth/me", async () => {
    api.fetchAuthConfig.mockResolvedValue({ auth_enabled: false, initialised: false });
    renderAuth();
    await waitFor(() => expect(current.status).toBe("disabled"));
    expect(api.fetchMe).not.toHaveBeenCalled();
  });
});

describe("status from /auth/me", () => {
  it("401 -> anonymous", async () => {
    api.fetchMe.mockRejectedValue(new ApiError(401, "unauthorized"));
    renderAuth();
    await waitFor(() => expect(current.status).toBe("anonymous"));
    expect(current.user).toBeNull();
  });

  it("503 -> uninitialised", async () => {
    api.fetchMe.mockRejectedValue(new ApiError(503, "not initialised"));
    renderAuth();
    await waitFor(() => expect(current.status).toBe("uninitialised"));
  });

  it("success -> authenticated with user object", async () => {
    api.fetchMe.mockResolvedValue(session());
    renderAuth();
    await waitFor(() => expect(current.status).toBe("authenticated"));
    expect(current.user).toEqual({ username: "admin", display_name: "Admin" });
    expect(current.csrf).toBe("tok");
    expect(current.mustChangePassword).toBe(false);
  });
});

describe("useCan", () => {
  it("allowed, denied with required role, unknown", async () => {
    api.fetchMe.mockResolvedValue(session());
    renderAuth(["data.view", "policy.pin", "no.such.perm"]);
    await waitFor(() => expect(current.status).toBe("authenticated"));
    expect(canOf("data.view").allowed).toBe(true);
    expect(canOf("policy.pin")).toMatchObject({
      allowed: false,
      reason: "auth.reason.requires_role",
      requiredRole: "lead",
    });
    expect(canOf("no.such.perm").reason).toBe("auth.reason.unknown_permission");
  });

  it("not authenticated -> not_authenticated", async () => {
    api.fetchMe.mockRejectedValue(new ApiError(401, "x"));
    renderAuth(["data.view"]);
    await waitFor(() => expect(current.status).toBe("anonymous"));
    expect(canOf("data.view").reason).toBe("auth.reason.not_authenticated");
  });
});

describe("role table", () => {
  it("lowest role is computed from the table", () => {
    expect(ROLE_ORDER).toEqual(["viewer", "operator", "engineer", "lead", "admin"]);
    expect(PERMISSION_LOWEST_ROLE["gw.reject"]).toBe("viewer");
    expect(PERMISSION_LOWEST_ROLE["users.manage"]).toBe("admin");
    expect(PERMISSION_LOWEST_ROLE["analysis.run"]).toBe("operator");
    expect(PERMISSION_LOWEST_ROLE["policy.edit"]).toBe("engineer");
    expect(PERMISSION_LOWEST_ROLE["policy.reload"]).toBe("lead");
  });

  it("embedded table equals schemas/auth-roles.default.json", () => {
    const fromJson: Record<string, string[]> = Object.fromEntries(
      Object.entries(rolesJson.roles).map(([role, def]) => [role, def.permissions]),
    );
    expect(Object.keys(DEFAULT_ROLE_PERMISSIONS).sort()).toEqual(Object.keys(fromJson).sort());
    for (const [role, perms] of Object.entries(fromJson)) {
      expect(DEFAULT_ROLE_PERMISSIONS[role]).toEqual(perms);
    }
  });
});

describe("login, mustChangePassword, logout", () => {
  it("login success sets state", async () => {
    api.fetchMe.mockRejectedValue(new ApiError(401, "x"));
    api.login.mockResolvedValue(session({ roles: ["admin"] }));
    renderAuth();
    await waitFor(() => expect(current.status).toBe("anonymous"));
    await act(async () => {
      await current.login({ username: "admin", password: "pw" });
    });
    expect(current.status).toBe("authenticated");
    expect(current.roles).toEqual(["admin"]);
    expect(current.user?.display_name).toBe("Admin");
  });

  it("must_change_password true is exposed", async () => {
    api.fetchMe.mockResolvedValue(session({ must_change_password: true }));
    renderAuth();
    await waitFor(() => expect(current.mustChangePassword).toBe(true));
  });

  it("password-change-required event sets it; refresh resets it", async () => {
    api.fetchMe.mockResolvedValue(session());
    renderAuth();
    await waitFor(() => expect(current.status).toBe("authenticated"));
    act(() => listeners.passwordChange.forEach((fn) => fn()));
    expect(current.mustChangePassword).toBe(true);
    await act(async () => {
      await current.refresh();
    });
    expect(current.mustChangePassword).toBe(false);
  });

  it("logout clears state even if the request rejects", async () => {
    api.fetchMe.mockResolvedValue(session());
    api.logout.mockRejectedValue(new Error("network"));
    renderAuth();
    await waitFor(() => expect(current.status).toBe("authenticated"));
    await act(async () => {
      await current.logout();
    });
    expect(current.status).toBe("anonymous");
    expect(current.user).toBeNull();
    expect(current.permissions).toEqual([]);
  });

  it("unauthorized event clears the session", async () => {
    api.fetchMe.mockResolvedValue(session());
    renderAuth();
    await waitFor(() => expect(current.status).toBe("authenticated"));
    act(() => listeners.unauthorized.forEach((fn) => fn()));
    expect(current.status).toBe("anonymous");
  });
});

describe("requestStepUp", () => {
  beforeEach(() => api.fetchMe.mockResolvedValue(session()));

  it("opens the dialog and resolves true on success", async () => {
    renderAuth();
    await waitFor(() => expect(current.status).toBe("authenticated"));
    api.stepUp.mockResolvedValue({ ok: true, valid_for_s: 300 });
    let result: Promise<boolean> = Promise.resolve(false);
    act(() => {
      result = current.requestStepUp();
    });
    expect(await screen.findByTestId("stepup-dialog")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("auth.stepup.passwordLabel"), { target: { value: "pw" } });
    fireEvent.click(screen.getByTestId("stepup-submit"));
    await expect(result).resolves.toBe(true);
    await waitFor(() => expect(screen.queryByTestId("stepup-dialog")).toBeNull());
  });

  it("resolves false on cancel", async () => {
    renderAuth();
    await waitFor(() => expect(current.status).toBe("authenticated"));
    let result: Promise<boolean> = Promise.resolve(true);
    act(() => {
      result = current.requestStepUp();
    });
    fireEvent.click(await screen.findByText("auth.stepup.cancelButton"));
    await expect(result).resolves.toBe(false);
  });
});

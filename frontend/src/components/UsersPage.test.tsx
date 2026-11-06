// frontend/src/components/UsersPage.test.tsx
/**
 * Tests for the user administration console: create/edit/reset/delete flows, server errors that
 * keep forms open, self-protection, client-side validation and modal accessibility.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, createUser, deleteUser, fetchUsers, patchUser } from "../authApi";
import type { UserRecord } from "../authApi";
import { useAuth, useCan } from "../AuthContext";
import { UsersPage } from "../UsersPage";

vi.mock("../authApi", async () => {
  const actual = await vi.importActual<typeof import("../authApi")>("../authApi");
  return { ...actual, fetchUsers: vi.fn(), createUser: vi.fn(), patchUser: vi.fn(), deleteUser: vi.fn() };
});
vi.mock("../AuthContext", () => ({ useAuth: vi.fn(), useCan: vi.fn() }));

const t = (key: string, params?: Record<string, string | number>) =>
  params ? `${key} ${JSON.stringify(params)}` : key;

const FUTURE = "2999-01-01T00:00:00Z";

function makeUser(username: string, overrides: Partial<UserRecord> = {}): UserRecord {
  return {
    username,
    display_name: username.toUpperCase(),
    roles: ["viewer"],
    disabled: false,
    must_change_password: false,
    created_at: "2026-10-01T08:00:00Z",
    password_changed_at: "2026-10-02T08:00:00Z",
    failed_logins: 0,
    locked_until: null,
    source: "local",
    ...overrides,
  };
}

const USERS: UserRecord[] = [
  makeUser("admin", { roles: ["admin"] }),
  makeUser("boss", { roles: ["admin"] }),
  makeUser("alice", { roles: ["operator"], failed_logins: 5, locked_until: FUTURE }),
];

function mockAuth(username: string | null = "admin"): void {
  const user = username ? { username, display_name: "Admin" } : null;
  vi.mocked(useAuth).mockReturnValue({ status: "authenticated", user, roles: ["admin"] } as unknown as ReturnType<typeof useAuth>);
  vi.mocked(useCan).mockReturnValue({ allowed: true, reason: "" });
}

async function renderPage(): Promise<void> {
  render(<UsersPage t={t} />);
  await screen.findByTestId("user-row-admin");
}

function fillCreate(values: { username?: string; name?: string; password?: string }): void {
  fireEvent.change(screen.getByLabelText("auth.users.username"), { target: { value: values.username ?? "dave" } });
  fireEvent.change(screen.getByLabelText("auth.users.displayName"), { target: { value: values.name ?? "Dave" } });
  fireEvent.change(screen.getByLabelText("auth.users.password"), { target: { value: values.password ?? "a-long-password-1" } });
}

function openCreate(): HTMLElement {
  const opener = screen.getByTestId("open-create-user");
  opener.focus();
  fireEvent.click(opener);
  return opener;
}

beforeEach(() => {
  vi.resetAllMocks();
  mockAuth();
  vi.mocked(fetchUsers).mockResolvedValue({ users: USERS });
});

describe("UsersPage listing", () => {
  it("shows the denied notice without users.manage", () => {
    vi.mocked(useCan).mockReturnValue({ allowed: false, reason: "x", requiredRole: "admin" });
    render(<UsersPage t={t} />);
    expect(screen.getByText("auth.users.denied")).toBeInTheDocument();
    expect(fetchUsers).not.toHaveBeenCalled();
  });

  it("renders users with extra fields and flags only currently locked accounts", async () => {
    await renderPage();
    expect(within(screen.getByTestId("user-row-alice")).getByText("auth.users.locked")).toBeInTheDocument();
    expect(within(screen.getByTestId("user-row-boss")).queryByText("auth.users.locked")).not.toBeInTheDocument();
  });

  it("ignores a locked_until timestamp in the past", async () => {
    vi.mocked(fetchUsers).mockResolvedValue({ users: [...USERS, makeUser("old", { locked_until: "2001-01-01T00:00:00Z" })] });
    await renderPage();
    expect(within(await screen.findByTestId("user-row-old")).queryByText("auth.users.locked")).not.toBeInTheDocument();
  });
});

describe("UsersPage create", () => {
  it("sends the exact body, closes the form and refreshes the list", async () => {
    vi.mocked(createUser).mockResolvedValue(makeUser("dave"));
    await renderPage();
    openCreate();
    fillCreate({});
    fireEvent.click(screen.getByTestId("create-user-submit"));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(createUser).toHaveBeenCalledWith({
      username: "dave",
      display_name: "Dave",
      roles: ["viewer"],
      password: "a-long-password-1",
      must_change_password: true,
    });
    expect(fetchUsers).toHaveBeenCalledTimes(2);
  });

  it("keeps the form open and shows the server message on 422", async () => {
    vi.mocked(createUser).mockRejectedValue(new ApiError(422, "Password must be at least 12 characters long."));
    await renderPage();
    openCreate();
    fillCreate({});
    fireEvent.click(screen.getByTestId("create-user-submit"));
    const dialog = screen.getByRole("dialog");
    await waitFor(() => expect(within(dialog).getByTestId("modal-error")).toHaveTextContent("Password must be at least 12 characters long."));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText("auth.users.username")).toHaveValue("dave");
  });

  it("keeps the form open on 409 user exists", async () => {
    vi.mocked(createUser).mockRejectedValue(new ApiError(409, "user exists"));
    await renderPage();
    openCreate();
    fillCreate({});
    fireEvent.click(screen.getByTestId("create-user-submit"));
    await waitFor(() => expect(within(screen.getByRole("dialog")).getByTestId("modal-error")).toHaveTextContent("user exists"));
    expect(fetchUsers).toHaveBeenCalledTimes(1);
  });
});

describe("UsersPage create validation", () => {
  async function submitInvalid(values: { username?: string; name?: string; password?: string }): Promise<void> {
    await renderPage();
    openCreate();
    fillCreate(values);
    fireEvent.click(screen.getByTestId("create-user-submit"));
  }

  it("requires a display name", async () => {
    await submitInvalid({ name: "   " });
    expect(screen.getByText("auth.users.displayNameRequired")).toBeInTheDocument();
    expect(createUser).not.toHaveBeenCalled();
  });

  it("validates the username against the server pattern", async () => {
    await submitInvalid({ username: "Bad Name" });
    expect(screen.getByText("auth.users.usernameInvalid")).toBeInTheDocument();
    expect(createUser).not.toHaveBeenCalled();
  });

  it("blocks passwords shorter than MIN_PASSWORD_LENGTH without a request", async () => {
    await submitInvalid({ password: "short" });
    expect(screen.getByText('auth.users.passwordTooShort {"min":12}')).toBeInTheDocument();
    expect(createUser).not.toHaveBeenCalled();
  });

  it("requires at least one role", async () => {
    await renderPage();
    openCreate();
    fillCreate({});
    fireEvent.click(screen.getByTestId("role-checkbox-viewer"));
    fireEvent.click(screen.getByTestId("create-user-submit"));
    expect(screen.getByText("auth.users.rolesRequired")).toBeInTheDocument();
    expect(createUser).not.toHaveBeenCalled();
  });
});

describe("UsersPage reset password", () => {
  it("blocks a short password and keeps the dialog open on server error", async () => {
    vi.mocked(patchUser).mockRejectedValue(new ApiError(422, "unknown role"));
    await renderPage();
    fireEvent.click(screen.getByTestId("reset-pwd-alice"));
    fireEvent.change(screen.getByLabelText("auth.users.password"), { target: { value: "short" } });
    fireEvent.click(screen.getByTestId("save-reset-pwd-button"));
    expect(screen.getByText('auth.users.passwordTooShort {"min":12}')).toBeInTheDocument();
    expect(patchUser).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("auth.users.password"), { target: { value: "long-enough-pass1" } });
    fireEvent.click(screen.getByTestId("save-reset-pwd-button"));
    await waitFor(() => expect(within(screen.getByRole("dialog")).getByTestId("modal-error")).toHaveTextContent("unknown role"));
    expect(patchUser).toHaveBeenCalledWith("alice", { password: "long-enough-pass1", must_change_password: true });
  });
});

describe("UsersPage last admin protection", () => {
  const LAST_ADMIN = new ApiError(409, "cannot remove the last admin");

  it("keeps the roles dialog open with the error", async () => {
    vi.mocked(patchUser).mockRejectedValue(LAST_ADMIN);
    await renderPage();
    fireEvent.click(screen.getByTestId("edit-roles-boss"));
    fireEvent.click(screen.getByTestId("role-checkbox-viewer"));
    fireEvent.click(screen.getByTestId("save-roles-button"));
    await waitFor(() => expect(within(screen.getByRole("dialog")).getByTestId("modal-error")).toHaveTextContent("cannot remove the last admin"));
  });

  it("shows the banner and keeps the list when disabling fails", async () => {
    vi.mocked(patchUser).mockRejectedValue(LAST_ADMIN);
    await renderPage();
    fireEvent.click(screen.getByTestId("toggle-disabled-boss"));
    expect(await screen.findByText(/cannot remove the last admin/)).toBeInTheDocument();
    expect(screen.getByTestId("user-row-boss")).toBeInTheDocument();
  });

  it("keeps the delete confirmation open with the error", async () => {
    vi.mocked(deleteUser).mockRejectedValue(LAST_ADMIN);
    await renderPage();
    fireEvent.click(screen.getByTestId("delete-boss"));
    fireEvent.click(screen.getByTestId("confirm-delete-button"));
    await waitFor(() => expect(within(screen.getByRole("dialog")).getByTestId("modal-error")).toHaveTextContent("cannot remove the last admin"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

describe("UsersPage self protection", () => {
  const SELF_TESTS = [
    ["reset-pwd-admin", "auth.users.cannotResetSelf"],
    ["toggle-disabled-admin", "auth.users.cannotDisableSelf"],
    ["delete-admin", "auth.users.cannotDeleteSelf"],
    ["edit-roles-admin", "auth.users.cannotEditOwnRoles"],
  ];

  it.each(SELF_TESTS)("disables %s on the own row with a reason", async (testId, reason) => {
    await renderPage();
    const button = screen.getByTestId(testId);
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button.parentElement).toHaveTextContent(reason);
    fireEvent.click(button);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(patchUser).not.toHaveBeenCalled();
  });

  it.each(SELF_TESTS)("keeps %s enabled on other users", async (testId) => {
    await renderPage();
    expect(screen.getByTestId(testId.replace("admin", "boss"))).not.toHaveAttribute("aria-disabled");
  });
});

describe("UsersPage modal accessibility", () => {
  const OPENERS: Array<[string, () => HTMLElement]> = [
    ["create", openCreate],
    ["edit roles", () => screen.getByTestId("edit-roles-boss")],
    ["reset password", () => screen.getByTestId("reset-pwd-boss")],
    ["delete", () => screen.getByTestId("delete-boss")],
  ];

  it.each(OPENERS)("%s dialog has ARIA labelling, closes on Escape and returns focus", async (_name, getOpener) => {
    await renderPage();
    const opener = getOpener();
    opener.focus();
    fireEvent.click(opener);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    const labelId = dialog.getAttribute("aria-labelledby") as string;
    expect(document.getElementById(labelId)?.textContent).toBeTruthy();
    fireEvent.keyDown(document.activeElement ?? dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("traps Tab inside the delete dialog", async () => {
    await renderPage();
    fireEvent.click(screen.getByTestId("delete-boss"));
    const confirm = screen.getByTestId("confirm-delete-button");
    confirm.focus();
    fireEvent.keyDown(confirm, { key: "Tab" });
    expect(within(screen.getByRole("dialog")).getAllByRole("button")[0]).toHaveFocus();
  });

  it("ignores Escape while the request is in flight", async () => {
    let resolveCreate: (u: UserRecord) => void = () => undefined;
    vi.mocked(createUser).mockReturnValue(new Promise<UserRecord>((resolve) => { resolveCreate = resolve; }));
    await renderPage();
    openCreate();
    fillCreate({});
    fireEvent.click(screen.getByTestId("create-user-submit"));
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    resolveCreate(makeUser("dave"));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

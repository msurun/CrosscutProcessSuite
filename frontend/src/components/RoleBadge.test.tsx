// frontend/src/components/RoleBadge.test.tsx
/**
 * Tests for RoleBadge inside a real AuthProvider with a mocked global fetch.
 * Covers display name, role chips, logout (also when the request fails) and text-only rendering.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../AuthContext";
import { RoleBadge } from "./RoleBadge";

const LABELS: Record<string, string> = {
  "auth.role.operator": "Operator",
  "auth.role.engineer": "Engineer",
  "auth.logout": "Log out",
  "auth.userBadge": "Signed-in user",
};
const t = (key: string) => LABELS[key] ?? key;

function session(user: { username: string; display_name: string }, roles = ["operator", "engineer"]) {
  return { user, roles, permissions: [], csrf: "tok", must_change_password: false };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

type LogoutMode = "ok" | "reject" | "500";

function mockFetch(me: unknown, logout: LogoutMode = "ok"): ReturnType<typeof vi.fn> {
  const fn = vi.fn(async (url: string) => {
    if (url.endsWith("/auth/me")) return me ? jsonResponse(me) : jsonResponse({ detail: "no" }, 401);
    if (url.endsWith("/auth/logout")) {
      if (logout === "reject") throw new TypeError("network down");
      return logout === "500" ? jsonResponse({ detail: "boom" }, 500) : jsonResponse({ ok: true });
    }
    return jsonResponse({}, 404);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function renderBadge() {
  return render(
    <AuthProvider t={t}>
      <RoleBadge t={t} />
    </AuthProvider>
  );
}

beforeEach(() => vi.unstubAllGlobals());
afterEach(() => vi.unstubAllGlobals());

describe("RoleBadge", () => {
  it("shows display name with username as title, plus translated role chips", async () => {
    mockFetch(session({ username: "jdoe", display_name: "Jane Doe" }));
    renderBadge();
    const name = await screen.findByTestId("role-badge-user");
    expect(name).toHaveTextContent("Jane Doe");
    expect(name).toHaveAttribute("title", "jdoe");
    expect(screen.getByText("Operator")).toBeInTheDocument();
    expect(screen.getByText("Engineer")).toBeInTheDocument();
  });

  it("falls back to username when the display name is blank", async () => {
    mockFetch(session({ username: "jdoe", display_name: "  " }));
    renderBadge();
    expect(await screen.findByTestId("role-badge-user")).toHaveTextContent("jdoe");
  });

  it("is hidden when nobody is signed in", async () => {
    const fetchMock = mockFetch(null);
    renderBadge();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByTestId("role-badge-user")).not.toBeInTheDocument());
    expect(screen.queryByRole("region")).not.toBeInTheDocument();
  });

  it("calls the onLogout handler when given", () => {
    const onLogout = vi.fn();
    render(<RoleBadge t={t} user={{ username: "a", display_name: "A" }} roles={["operator"]} onLogout={onLogout} />);
    fireEvent.click(screen.getByTestId("role-badge-logout"));
    expect(onLogout).toHaveBeenCalledTimes(1);
  });

  it.each<LogoutMode>(["ok", "reject", "500"])("clears the session on logout (request: %s)", async (mode) => {
    mockFetch(session({ username: "jdoe", display_name: "Jane Doe" }), mode);
    renderBadge();
    fireEvent.click(await screen.findByTestId("role-badge-logout"));
    await waitFor(() => expect(screen.queryByTestId("role-badge-user")).not.toBeInTheDocument());
  });

  it("renders HTML in names as plain text", async () => {
    const evil = "<img src=x onerror=alert(1)>";
    mockFetch(session({ username: "u<b>", display_name: evil }));
    const { container } = renderBadge();
    expect(await screen.findByTestId("role-badge-user")).toHaveTextContent(evil);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
  });
});

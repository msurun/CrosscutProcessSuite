// frontend/src/http.test.ts
// Tests for the shared request layer: credentials, CSRF header, 401 / 428 / 403 reactions.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setCsrfToken, setStepUpHandler, subscribePasswordChangeRequired, subscribeUnauthorized } from "./authApi";
import { apiFetch } from "./http";

function reply(status: number, detail?: string): Response {
  const body = detail === undefined ? "{}" : JSON.stringify({ detail });
  return new Response(body, { status, headers: { "Content-Type": "application/json" } });
}

function headersOf(spy: ReturnType<typeof vi.fn>, index = 0): Record<string, string> {
  const init = spy.mock.calls[index][1] as RequestInit;
  return (init.headers ?? {}) as Record<string, string>;
}

describe("apiFetch", () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    setCsrfToken(null);
    setStepUpHandler(null);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    setCsrfToken(null);
    setStepUpHandler(null);
  });

  it("sends same-origin credentials and no CSRF header on GET", async () => {
    setCsrfToken("tok");
    fetchSpy.mockResolvedValue(reply(200));
    await apiFetch("/api/x");
    const init = fetchSpy.mock.calls[0][1] as RequestInit;
    expect(init.credentials).toBe("same-origin");
    expect(headersOf(fetchSpy)).not.toHaveProperty("X-Crosscut-CSRF");
  });

  it("adds the CSRF header on unsafe methods and keeps the caller headers", async () => {
    setCsrfToken("tok");
    fetchSpy.mockResolvedValue(reply(200));
    await apiFetch("/api/x", { method: "post", headers: { "Content-Type": "application/json" }, body: "{}" });
    expect(headersOf(fetchSpy)).toEqual({ "Content-Type": "application/json", "X-Crosscut-CSRF": "tok" });
  });

  it("adds no CSRF header when there is no token (auth off)", async () => {
    fetchSpy.mockResolvedValue(reply(200));
    await apiFetch("/api/x", { method: "DELETE" });
    expect(headersOf(fetchSpy)).toEqual({});
  });

  it("fires the session-ended event on 401 and returns the response", async () => {
    const listener = vi.fn();
    const off = subscribeUnauthorized(listener);
    fetchSpy.mockResolvedValue(reply(401, "not authenticated"));
    const response = await apiFetch("/api/x");
    off();
    expect(response.status).toBe(401);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("opens the step-up flow on 428 and retries exactly once", async () => {
    setCsrfToken("tok");
    const handler = vi.fn().mockResolvedValue(true);
    setStepUpHandler(handler);
    fetchSpy.mockResolvedValueOnce(reply(428, "step_up_required")).mockResolvedValueOnce(reply(200));
    const response = await apiFetch("/api/x", { method: "POST", body: "{}" });
    expect(response.status).toBe(200);
    expect(handler).toHaveBeenCalledTimes(1);
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(headersOf(fetchSpy, 1)["X-Crosscut-CSRF"]).toBe("tok");
  });

  it("does not loop when the retry is challenged again", async () => {
    setStepUpHandler(vi.fn().mockResolvedValue(true));
    fetchSpy.mockResolvedValue(reply(428, "step_up_required"));
    const response = await apiFetch("/api/x", { method: "POST" });
    expect(response.status).toBe(428);
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it("returns the 428 untouched when the step-up is cancelled", async () => {
    setStepUpHandler(vi.fn().mockResolvedValue(false));
    fetchSpy.mockResolvedValue(reply(428, "step_up_required"));
    const response = await apiFetch("/api/x", { method: "POST" });
    expect(response.status).toBe(428);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("fires the password-change event on 403 password_change_required only", async () => {
    const listener = vi.fn();
    const off = subscribePasswordChangeRequired(listener);
    fetchSpy.mockResolvedValueOnce(reply(403, "forbidden")).mockResolvedValueOnce(reply(403, "password_change_required"));
    await apiFetch("/api/x");
    expect(listener).not.toHaveBeenCalled();
    const response = await apiFetch("/api/x");
    off();
    expect(listener).toHaveBeenCalledTimes(1);
    await expect(response.json()).resolves.toEqual({ detail: "password_change_required" });
  });
});

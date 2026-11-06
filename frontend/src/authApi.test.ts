// frontend/src/authApi.test.ts
// Unit tests for the authentication and user management API client.
// Validates session verification, REST contracts, CSRF enforcement,
// event notifications (401, 403 password change), and step-up authentication retries.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  AuthSession,
  changePassword,
  createUser,
  deleteUser,
  fetchMe,
  fetchUsers,
  getCsrfToken,
  isValidAuthSession,
  login,
  logout,
  patchUser,
  setCsrfToken,
  setStepUpHandler,
  stepUp,
  subscribePasswordChangeRequired,
  subscribeUnauthorized,
} from "./authApi";

const TEST_CSRF_TOKEN = "test-csrf-token-xyz";

function createValidSessionFixture(overrides: Partial<AuthSession> = {}): AuthSession {
  return {
    user: {
      username: "admin",
      display_name: "Admin User",
    },
    roles: ["admin"],
    permissions: ["analysis.run"],
    csrf: TEST_CSRF_TOKEN,
    must_change_password: false,
    stepup_valid: false,
    ...overrides,
  };
}

function createJsonResponse(body: unknown, status = 200, headersInit?: Record<string, string>): Response {
  const headers = new Headers(headersInit);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return new Response(JSON.stringify(body), { status, headers });
}

function getCapturedRequest(fetchSpy: { mock: { calls: unknown[][] } }, callIndex = 0): {
  url: string;
  init: RequestInit;
  headers: Record<string, string>;
  parsedBody: unknown;
} {
  const call = fetchSpy.mock.calls[callIndex];
  const url = String(call[0]);
  const init = (call[1] ?? {}) as RequestInit;
  const headersRecord: Record<string, string> = {};

  if (init.headers instanceof Headers) {
    init.headers.forEach((value, key) => {
      headersRecord[key.toLowerCase()] = value;
    });
  } else if (Array.isArray(init.headers)) {
    for (const [key, value] of init.headers) {
      headersRecord[key.toLowerCase()] = value;
    }
  } else if (init.headers && typeof init.headers === "object") {
    for (const [key, value] of Object.entries(init.headers)) {
      headersRecord[key.toLowerCase()] = String(value);
    }
  }

  const parsedBody = typeof init.body === "string" ? JSON.parse(init.body) : undefined;
  return { url, init, headers: headersRecord, parsedBody };
}

describe("authApi", () => {
  beforeEach(() => {
    setCsrfToken(null);
    setStepUpHandler(null);
    vi.restoreAllMocks();
  });

  afterEach(() => {
    setCsrfToken(null);
    setStepUpHandler(null);
    vi.restoreAllMocks();
  });

  describe("isValidAuthSession", () => {
    it("accepts a session conforming to the real backend shape", () => {
      const valid = createValidSessionFixture();
      expect(isValidAuthSession(valid)).toBe(true);
    });

    it("accepts a session when optional stepup_valid is omitted", () => {
      const valid = createValidSessionFixture();
      delete (valid as Partial<AuthSession>).stepup_valid;
      expect(isValidAuthSession(valid)).toBe(true);
    });

    it("rejects an invalid payload where user is a legacy string", () => {
      const invalid = {
        user: "admin",
        roles: ["admin"],
        permissions: [],
        csrf: TEST_CSRF_TOKEN,
        must_change_password: false,
      };
      expect(isValidAuthSession(invalid)).toBe(false);
    });

    it("rejects a payload when user object has an empty username", () => {
      const invalid = createValidSessionFixture({
        user: { username: "", display_name: "Admin" },
      });
      expect(isValidAuthSession(invalid)).toBe(false);
    });

    it("rejects a payload missing the mandatory must_change_password boolean", () => {
      const invalid = createValidSessionFixture();
      delete (invalid as Partial<AuthSession>).must_change_password;
      expect(isValidAuthSession(invalid)).toBe(false);
    });

    it("rejects null or non-object values", () => {
      expect(isValidAuthSession(null)).toBe(false);
      expect(isValidAuthSession(undefined)).toBe(false);
      expect(isValidAuthSession("session")).toBe(false);
      expect(isValidAuthSession(12345)).toBe(false);
    });
  });

  describe("Endpoints and HTTP Contract", () => {
    it("login sends POST without CSRF header and records the returned token", async () => {
      const session = createValidSessionFixture();
      const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(createJsonResponse(session));

      const payload = { username: "operator1", password: "validpassword123" };
      const result = await login(payload);

      expect(result).toEqual(session);
      expect(getCsrfToken()).toBe(TEST_CSRF_TOKEN);

      const req = getCapturedRequest(fetchSpy);
      expect(req.url).toBe("/api/auth/login");
      expect(req.init.method).toBe("POST");
      expect(req.parsedBody).toEqual(payload);
      expect(req.headers["x-crosscut-csrf"]).toBeUndefined();
    });

    it("logout sends POST with CSRF header, parses ok response, and clears token", async () => {
      setCsrfToken(TEST_CSRF_TOKEN);
      const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(createJsonResponse({ ok: true }));

      const res = await logout();
      expect(res).toEqual({ ok: true });
      expect(getCsrfToken()).toBeNull();

      const req = getCapturedRequest(fetchSpy);
      expect(req.url).toBe("/api/auth/logout");
      expect(req.init.method).toBe("POST");
      expect(req.headers["x-crosscut-csrf"]).toBe(TEST_CSRF_TOKEN);
    });

    it("fetchMe sends GET without CSRF header and updates token", async () => {
      const session = createValidSessionFixture({ csrf: "refreshed-csrf" });
      const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(createJsonResponse(session));

      const result = await fetchMe();
      expect(result).toEqual(session);
      expect(getCsrfToken()).toBe("refreshed-csrf");

      const req = getCapturedRequest(fetchSpy);
      expect(req.url).toBe("/api/auth/me");
      expect(req.init.method).toBe("GET");
      expect(req.headers["x-crosscut-csrf"]).toBeUndefined();
    });

    it("changePassword sends POST with CSRF and returns OkResponse", async () => {
      setCsrfToken(TEST_CSRF_TOKEN);
      const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(createJsonResponse({ ok: true }));

      const payload = { old_password: "oldPassword123!", new_password: "newPassword123!" };
      const res = await changePassword(payload);

      expect(res).toEqual({ ok: true });
      const req = getCapturedRequest(fetchSpy);
      expect(req.url).toBe("/api/auth/password");
      expect(req.init.method).toBe("POST");
      expect(req.parsedBody).toEqual(payload);
      expect(req.headers["x-crosscut-csrf"]).toBe(TEST_CSRF_TOKEN);
    });

    it("stepUp sends POST with CSRF and returns ok with valid_for_s duration", async () => {
      setCsrfToken(TEST_CSRF_TOKEN);
      const expectedResult = { ok: true, valid_for_s: 300 };
      const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(createJsonResponse(expectedResult));

      const payload = { password: "stepUpSecretPassword1" };
      const res = await stepUp(payload);

      expect(res).toEqual(expectedResult);
      const req = getCapturedRequest(fetchSpy);
      expect(req.url).toBe("/api/auth/stepup");
      expect(req.init.method).toBe("POST");
      expect(req.parsedBody).toEqual(payload);
      expect(req.headers["x-crosscut-csrf"]).toBe(TEST_CSRF_TOKEN);
    });

    it("fetchUsers sends GET without CSRF header and returns user list", async () => {
      const usersData = { users: [{ username: "admin", display_name: "Admin", roles: ["admin"], disabled: false, must_change_password: false }] };
      const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(createJsonResponse(usersData));

      const res = await fetchUsers();
      expect(res).toEqual(usersData);

      const req = getCapturedRequest(fetchSpy);
      expect(req.url).toBe("/api/auth/users");
      expect(req.init.method).toBe("GET");
      expect(req.headers["x-crosscut-csrf"]).toBeUndefined();
    });

    it("createUser sends POST with CSRF and handles HTTP 201 response", async () => {
      setCsrfToken(TEST_CSRF_TOKEN);
      const createdRecord = {
        username: "operator2",
        display_name: "Operator Two",
        roles: ["operator"],
        disabled: false,
        must_change_password: true,
      };
      const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(createJsonResponse(createdRecord, 201));

      const payload = {
        username: "operator2",
        display_name: "Operator Two",
        roles: ["operator"],
        password: "TempPassword123!",
        must_change_password: true,
      };
      const res = await createUser(payload);

      expect(res).toEqual(createdRecord);
      const req = getCapturedRequest(fetchSpy);
      expect(req.url).toBe("/api/auth/users");
      expect(req.init.method).toBe("POST");
      expect(req.parsedBody).toEqual(payload);
      expect(req.headers["x-crosscut-csrf"]).toBe(TEST_CSRF_TOKEN);
    });

    it("patchUser sends PATCH with CSRF to the encoded username path", async () => {
      setCsrfToken(TEST_CSRF_TOKEN);
      const updatedRecord = {
        username: "user/with special chars",
        display_name: "Patched Name",
        roles: ["operator"],
        disabled: true,
        must_change_password: false,
      };
      const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(createJsonResponse(updatedRecord));

      const payload = { display_name: "Patched Name", disabled: true };
      const res = await patchUser("user/with special chars", payload);

      expect(res).toEqual(updatedRecord);
      const req = getCapturedRequest(fetchSpy);
      expect(req.url).toBe("/api/auth/users/user%2Fwith%20special%20chars");
      expect(req.init.method).toBe("PATCH");
      expect(req.parsedBody).toEqual(payload);
      expect(req.headers["x-crosscut-csrf"]).toBe(TEST_CSRF_TOKEN);
    });

    it("deleteUser sends DELETE with CSRF and returns OkResponse on 200", async () => {
      setCsrfToken(TEST_CSRF_TOKEN);
      const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(createJsonResponse({ ok: true }, 200));

      const res = await deleteUser("target_operator");
      expect(res).toEqual({ ok: true });

      const req = getCapturedRequest(fetchSpy);
      expect(req.url).toBe("/api/auth/users/target_operator");
      expect(req.init.method).toBe("DELETE");
      expect(req.headers["x-crosscut-csrf"]).toBe(TEST_CSRF_TOKEN);
    });
  });

  describe("Step-Up Authentication (428)", () => {
    it("retries request exactly once with identical options when handler resolves true", async () => {
      setCsrfToken(TEST_CSRF_TOKEN);
      const stepUpMock = vi.fn().mockResolvedValue(true);
      setStepUpHandler(stepUpMock);

      const fetchSpy = vi.spyOn(globalThis, "fetch")
        .mockResolvedValueOnce(createJsonResponse({ detail: "step_up_required" }, 428))
        .mockResolvedValueOnce(createJsonResponse({ ok: true }, 200));

      const payload = { old_password: "old", new_password: "new" };
      const res = await changePassword(payload);

      expect(res).toEqual({ ok: true });
      expect(stepUpMock).toHaveBeenCalledTimes(1);
      expect(fetchSpy).toHaveBeenCalledTimes(2);

      const firstReq = getCapturedRequest(fetchSpy, 0);
      const retryReq = getCapturedRequest(fetchSpy, 1);
      expect(firstReq.url).toBe(retryReq.url);
      expect(firstReq.init.method).toBe(retryReq.init.method);
      expect(firstReq.parsedBody).toEqual(retryReq.parsedBody);
      expect(firstReq.headers["x-crosscut-csrf"]).toBe(retryReq.headers["x-crosscut-csrf"]);
    });

    it("throws 428 ApiError immediately without retry when handler resolves false", async () => {
      setCsrfToken(TEST_CSRF_TOKEN);
      const stepUpMock = vi.fn().mockResolvedValue(false);
      setStepUpHandler(stepUpMock);

      const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        createJsonResponse({ detail: "step_up_required" }, 428)
      );

      await expect(changePassword({ old_password: "old", new_password: "new" })).rejects.toMatchObject({
        name: "ApiError",
        status: 428,
        detail: "step_up_required",
      });
      expect(stepUpMock).toHaveBeenCalledTimes(1);
      expect(fetchSpy).toHaveBeenCalledTimes(1);
    });

    it("throws 428 ApiError and stops without a third fetch on a second 428 response", async () => {
      setCsrfToken(TEST_CSRF_TOKEN);
      const stepUpMock = vi.fn().mockResolvedValue(true);
      setStepUpHandler(stepUpMock);

      const fetchSpy = vi.spyOn(globalThis, "fetch")
        .mockResolvedValueOnce(createJsonResponse({ detail: "step_up_required" }, 428))
        .mockResolvedValueOnce(createJsonResponse({ detail: "step_up_required" }, 428));

      await expect(changePassword({ old_password: "old", new_password: "new" })).rejects.toMatchObject({
        name: "ApiError",
        status: 428,
        detail: "step_up_required",
      });
      expect(stepUpMock).toHaveBeenCalledTimes(1);
      expect(fetchSpy).toHaveBeenCalledTimes(2);
    });
  });

  describe("Error Parsing and Rate Limits", () => {
    it("parses retry_after_s from Retry-After header on 429 response", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        createJsonResponse({ detail: "Too Many Requests" }, 429, { "Retry-After": "60" })
      );

      try {
        await login({ username: "op", password: "pwd" });
        expect.unreachable("Should have thrown ApiError");
      } catch (err: unknown) {
        expect(err).toBeInstanceOf(ApiError);
        const apiErr = err as ApiError;
        expect(apiErr.status).toBe(429);
        expect(apiErr.retry_after_s).toBe(60);
      }
    });

    it("falls back to body retry_after_s on 423 locked when Retry-After header is missing", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        createJsonResponse({ detail: "Account locked", retry_after_s: 45 }, 423)
      );

      try {
        await login({ username: "locked_user", password: "pwd" });
        expect.unreachable("Should have thrown ApiError");
      } catch (err: unknown) {
        expect(err).toBeInstanceOf(ApiError);
        const apiErr = err as ApiError;
        expect(apiErr.status).toBe(423);
        expect(apiErr.retry_after_s).toBe(45);
      }
    });

    it("joins FastAPI 422 validation error message list into a single detail string", async () => {
      setCsrfToken(TEST_CSRF_TOKEN);
      const validationPayload = {
        detail: [
          { loc: ["body", "password"], msg: "Password too short" },
          { loc: ["body", "password"], msg: "Must include numbers" },
        ],
      };
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(createJsonResponse(validationPayload, 422));

      try {
        await changePassword({ old_password: "old", new_password: "short" });
        expect.unreachable("Should have thrown ApiError");
      } catch (err: unknown) {
        expect(err).toBeInstanceOf(ApiError);
        const apiErr = err as ApiError;
        expect(apiErr.status).toBe(422);
        expect(apiErr.detail).toContain("Password too short");
        expect(apiErr.detail).toContain("Must include numbers");
      }
    });
  });

  describe("Listeners for 401 Unauthorized and 403 Password Change Required", () => {
    it("notifies password change required listeners and throws ApiError on 403 password_change_required", async () => {
      const listener = vi.fn();
      const unsubscribe = subscribePasswordChangeRequired(listener);
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        createJsonResponse({ detail: "password_change_required" }, 403)
      );

      await expect(fetchMe()).rejects.toMatchObject({
        name: "ApiError",
        status: 403,
        detail: "password_change_required",
      });

      expect(listener).toHaveBeenCalledTimes(1);
      unsubscribe();
    });

    it("notifies unauthorized listeners on 401 from standard endpoints", async () => {
      const listener = vi.fn();
      const unsubscribe = subscribeUnauthorized(listener);
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        createJsonResponse({ detail: "Token expired" }, 401)
      );

      await expect(fetchMe()).rejects.toThrow(ApiError);
      expect(listener).toHaveBeenCalledTimes(1);
      unsubscribe();
    });

    it("does NOT notify unauthorized listeners when 401 comes from login", async () => {
      const listener = vi.fn();
      const unsubscribe = subscribeUnauthorized(listener);
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        createJsonResponse({ detail: "Bad credentials" }, 401)
      );

      await expect(login({ username: "wrong", password: "pwd" })).rejects.toThrow(ApiError);
      expect(listener).not.toHaveBeenCalled();
      unsubscribe();
    });

    it("notifies unauthorized listeners and throws ApiError on 401 from stepup", async () => {
      setCsrfToken(TEST_CSRF_TOKEN);
      const listener = vi.fn();
      const unsubscribe = subscribeUnauthorized(listener);
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        createJsonResponse({ detail: "Invalid password for stepup" }, 401)
      );

      await expect(stepUp({ password: "wrongStepupPassword" })).rejects.toThrow(ApiError);
      expect(listener).toHaveBeenCalledTimes(1);
      unsubscribe();
    });
  });
});

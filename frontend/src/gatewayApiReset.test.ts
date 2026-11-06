// frontend/src/gatewayApiReset.test.ts
// resetKill: POST /api/gateway/kill/reset with the CSRF header; a 428 step-up is retried by apiFetch.

import { afterEach, describe, expect, it, vi } from "vitest";
import { setCsrfToken, setStepUpHandler } from "./authApi";
import { GatewayApiError, resetKill } from "./gatewayApi";

const ok = () => new Response(JSON.stringify({ ok: true }), { status: 200 });
const stepUp = () => new Response(JSON.stringify({ detail: "step_up_required" }), { status: 428 });

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
  setStepUpHandler(null);
});

describe("resetKill", () => {
  it("posts to /api/gateway/kill/reset with the CSRF header", async () => {
    const fetchMock = vi.fn(async () => ok());
    vi.stubGlobal("fetch", fetchMock);
    setCsrfToken("tok");
    await expect(resetKill()).resolves.toEqual({ ok: true });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/gateway/kill/reset");
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({ "X-Crosscut-CSRF": "tok" });
  });

  it("runs the step-up dialog on 428 and retries once", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(stepUp()).mockResolvedValueOnce(ok());
    vi.stubGlobal("fetch", fetchMock);
    const handler = vi.fn(async () => true);
    setStepUpHandler(handler);
    await resetKill();
    expect(handler).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("throws GatewayApiError with the detail when the gateway refuses (409)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "not killed" }), { status: 409 })));
    const error = await resetKill().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(GatewayApiError);
    expect(error).toMatchObject({ status: 409, message: "not killed" });
  });
});

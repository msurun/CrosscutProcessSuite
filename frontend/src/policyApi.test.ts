// frontend/src/policyApi.test.ts
/**
 * Unit tests for policyApi HTTP client functions (ADR 013, issues #46/#47).
 * Verifies request paths, HTTP verbs, payload serialization, error wrapping in PolicyError,
 * 404 draft absence, 422 validation details, and 409 concurrency conflicts.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  fetchDraftPolicy,
  fetchLivePolicy,
  pinPolicy,
  PolicyError,
  reloadPolicy,
  saveDraftPolicy,
  type DraftPolicyResponse,
  type LivePolicyResponse,
} from "./policyApi";
import { setStepUpHandler } from "./authApi";
import type { PolicyDocument } from "./policyModel";

function mockJsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const FIXTURE_DOC: PolicyDocument = {
  version: 1,
  mode: "advisory",
  targets: {
    "FIC101.SP": {
      limits: [10.0, 50.0],
      max_step: 2.0,
      max_rate_per_s: 1.0,
      min_interval_s: 1.0,
      allowed_loop_modes: ["CAS", "AUTO"],
      hold_off_s: 5.0,
      watchdog_s: 15.0,
      readback_tolerance: 0.2,
    },
  },
};

const LIVE_FIXTURE: LivePolicyResponse = {
  document: FIXTURE_DOC,
  pin: {
    digest: "live_digest_123",
    author: "engineer1",
    approver: "lead1",
    approved_at: "2026-11-05T12:00:00Z",
  },
  mode_cap: "advisory",
  digest: "live_digest_123",
};

const DRAFT_FIXTURE: DraftPolicyResponse = {
  document: FIXTURE_DOC,
  author: "engineer1",
  saved_at: "2026-11-05T13:00:00Z",
  digest: "draft_digest_456",
};

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("policyApi - fetchLivePolicy & fetchDraftPolicy", () => {
  it("fetchLivePolicy retrieves live pinned policy configuration", async () => {
    fetchMock.mockResolvedValueOnce(mockJsonResponse(200, LIVE_FIXTURE));
    const result = await fetchLivePolicy();
    expect(result).toEqual(LIVE_FIXTURE);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/gateway/policy");
  });

  it("fetchDraftPolicy retrieves current draft or throws 404 PolicyError when absent", async () => {
    fetchMock.mockResolvedValueOnce(mockJsonResponse(200, DRAFT_FIXTURE));
    const result = await fetchDraftPolicy();
    expect(result).toEqual(DRAFT_FIXTURE);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/gateway/policy/draft");

    fetchMock.mockResolvedValueOnce(mockJsonResponse(404, { detail: "no draft" }));
    await expect(fetchDraftPolicy()).rejects.toThrow(PolicyError);
  });
});

describe("policyApi - saveDraftPolicy", () => {
  it("saveDraftPolicy PUTs document and returns ok and digest", async () => {
    fetchMock.mockResolvedValueOnce(mockJsonResponse(200, { ok: true, digest: "saved_digest_789" }));
    const res = await saveDraftPolicy(FIXTURE_DOC);
    expect(res).toEqual({ ok: true, digest: "saved_digest_789" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/gateway/policy/draft");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual(FIXTURE_DOC);
  });

  it("saveDraftPolicy throws 422 PolicyError with backend validation message", async () => {
    fetchMock.mockResolvedValueOnce(
      mockJsonResponse(422, { detail: "Target FIC101.SP: limits[0] must be <= limits[1]" }),
    );
    await expect(saveDraftPolicy(FIXTURE_DOC)).rejects.toMatchObject({
      status: 422,
      detail: "Target FIC101.SP: limits[0] must be <= limits[1]",
    });
  });
});

describe("policyApi - pinPolicy", () => {
  it("pinPolicy POSTs digest and returns ok", async () => {
    fetchMock.mockResolvedValueOnce(mockJsonResponse(200, { ok: true }));
    const res = await pinPolicy("draft_digest_456");
    expect(res).toEqual({ ok: true });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/gateway/policy/pin");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ digest: "draft_digest_456" });
  });

  it("pinPolicy throws PolicyError on 409 draft_changed", async () => {
    fetchMock.mockResolvedValueOnce(mockJsonResponse(409, { detail: "draft_changed" }));
    await expect(pinPolicy("old_digest")).rejects.toMatchObject({
      status: 409,
      detail: "draft_changed",
    });
  });
});

describe("policyApi - reloadPolicy & error formatting", () => {
  it("reloadPolicy POSTs to reload route", async () => {
    fetchMock.mockResolvedValueOnce(mockJsonResponse(200, { ok: true }));
    const res = await reloadPolicy();
    expect(res).toEqual({ ok: true });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/gateway/policy/reload");
    expect(init.method).toBe("POST");
  });

  it("parses array error details from FastAPI", async () => {
    fetchMock.mockResolvedValueOnce(
      mockJsonResponse(422, { detail: [{ msg: "Field required" }, { msg: "Number invalid" }] }),
    );
    await expect(saveDraftPolicy(FIXTURE_DOC)).rejects.toMatchObject({
      status: 422,
      detail: "Field required; Number invalid",
    });
  });
});

describe("policyApi - step-up and gateway errors", () => {
  afterEach(() => setStepUpHandler(null));

  it("pin retries once after a completed step-up", async () => {
    setStepUpHandler(() => Promise.resolve(true));
    fetchMock
      .mockResolvedValueOnce(mockJsonResponse(428, { detail: "step_up_required" }))
      .mockResolvedValueOnce(mockJsonResponse(200, { ok: true }));
    await expect(pinPolicy("d")).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("pin fails with a 428 PolicyError when the step-up dialog is cancelled", async () => {
    setStepUpHandler(() => Promise.resolve(false));
    fetchMock.mockResolvedValueOnce(mockJsonResponse(428, { detail: "step_up_required" }));
    await expect(pinPolicy("d")).rejects.toMatchObject({ status: 428, detail: "step_up_required" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("keeps the 409 detail code, the 403 detail and a 504 without a JSON body", async () => {
    fetchMock.mockResolvedValueOnce(mockJsonResponse(409, { detail: "draft_bad_signature" }));
    await expect(pinPolicy("d")).rejects.toMatchObject({ status: 409, detail: "draft_bad_signature" });
    fetchMock.mockResolvedValueOnce(mockJsonResponse(403, { detail: "two_person_rule" }));
    await expect(pinPolicy("d")).rejects.toMatchObject({ status: 403, detail: "two_person_rule" });
    fetchMock.mockResolvedValueOnce(new Response("upstream timeout", { status: 504, statusText: "Gateway Timeout" }));
    await expect(reloadPolicy()).rejects.toMatchObject({ status: 504, detail: "Gateway Timeout" });
  });

  it("returns the optional file_digest field untouched", async () => {
    fetchMock.mockResolvedValueOnce(mockJsonResponse(200, { ...LIVE_FIXTURE, file_digest: "filebytes_1" }));
    await expect(fetchLivePolicy()).resolves.toMatchObject({ digest: "live_digest_123", file_digest: "filebytes_1" });
  });
});

// frontend/src/tuningApi.test.ts
// Request method, path, body and CSRF header of every tuning call, and the error shape.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setCsrfToken } from "./authApi";
import {
  approveTuningProposal,
  createTuningProposal,
  fetchTuningProposal,
  fetchTuningProposals,
  rejectTuningProposal,
  rollbackTuningProposal,
  TuningApiError,
} from "./tuningApi";
import { makeProposal } from "./tuningTestKit";

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(async () => json(200, makeProposal()));
  vi.stubGlobal("fetch", fetchMock);
  setCsrfToken("csrf-1");
});

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

function lastCall(): { url: string; init: RequestInit } {
  const [url, init] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1] as [string, RequestInit];
  return { url, init };
}

describe("reads", () => {
  it("lists without a filter by GET and without the CSRF header", async () => {
    fetchMock.mockResolvedValue(json(200, [makeProposal()]));
    await fetchTuningProposals();
    const { url, init } = lastCall();
    expect(url).toBe("/api/tuning/proposals");
    expect(init.method ?? "GET").toBe("GET");
    expect(init.headers).toBeUndefined();
  });

  it("puts the loop and status filters in the query", async () => {
    fetchMock.mockResolvedValue(json(200, []));
    await fetchTuningProposals({ loopId: "FIC 101", status: "queued" });
    expect(lastCall().url).toBe("/api/tuning/proposals?loop_id=FIC+101&status=queued");
  });

  it("reads one proposal by encoded id", async () => {
    await fetchTuningProposal("a/b");
    expect(lastCall().url).toBe("/api/tuning/proposals/a%2Fb");
  });
});

describe("writes", () => {
  it("creates a proposal: POST, JSON body, CSRF header", async () => {
    const body = { vendor_form: "abb_pidcc", method: "simc" as const, reason: "tune", dataset_id: "mill" };
    await createTuningProposal("FIC101", body);
    const { url, init } = lastCall();
    expect(url).toBe("/api/loops/FIC101/tuning/proposals");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual(body);
    expect(init.headers).toMatchObject({ "Content-Type": "application/json", "X-Crosscut-CSRF": "csrf-1" });
  });

  it("approves and rejects by POST with the CSRF header and no body", async () => {
    await approveTuningProposal("p1");
    expect(lastCall().url).toBe("/api/tuning/proposals/p1/approve");
    expect(lastCall().init.method).toBe("POST");
    expect(lastCall().init.body).toBeUndefined();
    expect(lastCall().init.headers).toMatchObject({ "X-Crosscut-CSRF": "csrf-1" });
    await rejectTuningProposal("p1");
    expect(lastCall().url).toBe("/api/tuning/proposals/p1/reject");
  });

  it("rolls back with and without a reason", async () => {
    await rollbackTuningProposal("p1", "worse");
    expect(lastCall().url).toBe("/api/tuning/proposals/p1/rollback");
    expect(JSON.parse(String(lastCall().init.body))).toEqual({ reason: "worse" });
    await rollbackTuningProposal("p1");
    expect(lastCall().init.body).toBeUndefined();
  });
});

describe("errors", () => {
  it("carries status and code of a string detail", async () => {
    fetchMock.mockResolvedValue(json(403, { detail: "self_approval" }));
    const error = await approveTuningProposal("p1").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(TuningApiError);
    expect(error).toMatchObject({ status: 403, code: "self_approval" });
  });

  it("reads code and message of an object detail (ProposalRefused)", async () => {
    fetchMock.mockResolvedValue(json(422, { detail: { code: "no_op", message: "gain would not change" } }));
    const error = await createTuningProposal("L", { vendor_form: "x", method: "simc", reason: "r", dataset_id: "d" }).catch(
      (e: unknown) => e,
    );
    expect(error).toMatchObject({ status: 422, code: "no_op", message: "gain would not change" });
  });

  it("has an empty code for a validation list or a non-JSON body", async () => {
    fetchMock.mockResolvedValue(json(422, { detail: [{ msg: "bad" }] }));
    expect(await fetchTuningProposals().catch((e: unknown) => e)).toMatchObject({ status: 422, code: "" });
    fetchMock.mockResolvedValue(new Response("oops", { status: 504 }));
    expect(await fetchTuningProposals().catch((e: unknown) => e)).toMatchObject({ status: 504, code: "" });
  });
});

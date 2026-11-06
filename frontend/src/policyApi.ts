// frontend/src/policyApi.ts
/**
 * Typed client for Write Gateway write-policy API routes (ADR 013, issues #46/#47).
 * Communicates with /gateway/policy endpoints via the shared apiFetch layer to support
 * policy review, draft persistence, cryptographic pin verification, and daemon reloading.
 */

import { apiFetch } from "./http";
import type { PolicyDocument, PolicyPinInfo } from "./policyModel";

export const API_PREFIX = "/api";

export interface LivePolicyResponse {
  document: PolicyDocument | null;
  pin: PolicyPinInfo | null;
  mode_cap: string | null;
  /** Canonical digest of the policy: THE policy digest shown to people. */
  digest: string | null;
  /** Digest of the file bytes (optional, newer servers); pin.digest is the same kind. */
  file_digest?: string | null;
}

export interface DraftPolicyResponse {
  document: PolicyDocument;
  author: string;
  saved_at: string;
  digest: string;
}

export interface PolicyActionResponse {
  ok: boolean;
  digest?: string;
}

export class PolicyError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "PolicyError";
    this.status = status;
    this.detail = detail;
  }
}

function formatDetailItem(item: unknown): string {
  if (typeof item === "string") return item;
  if (typeof item === "object" && item !== null && "msg" in item) {
    return String((item as { msg: unknown }).msg);
  }
  return JSON.stringify(item);
}

async function extractErrorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) return detail.map(formatDetailItem).join("; ");
    }
  } catch {
    // Non-JSON response body; fallback to status text
  }
  return response.statusText || `HTTP ${response.status}`;
}

async function requestPolicyJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(url, init);
  if (!response.ok) {
    const detail = await extractErrorDetail(response);
    throw new PolicyError(response.status, detail);
  }
  return (await response.json()) as T;
}

function jsonInit(method: string, body?: unknown): RequestInit {
  if (body === undefined) return { method };
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

/**
 * Fetches the currently pinned live policy and verification metadata from the gateway.
 */
export async function fetchLivePolicy(): Promise<LivePolicyResponse> {
  return requestPolicyJson<LivePolicyResponse>(`${API_PREFIX}/gateway/policy`);
}

/**
 * Fetches the active unpinned policy draft stored on the server.
 * Throws PolicyError with status 404 when no draft is currently open.
 */
export async function fetchDraftPolicy(): Promise<DraftPolicyResponse> {
  return requestPolicyJson<DraftPolicyResponse>(`${API_PREFIX}/gateway/policy/draft`);
}

/**
 * Persists an edited policy document as the server-side working draft.
 * Throws PolicyError with status 422 if the backend schema validation rejects the document.
 */
export async function saveDraftPolicy(
  document: PolicyDocument,
): Promise<{ ok: boolean; digest: string }> {
  return requestPolicyJson<{ ok: boolean; digest: string }>(
    `${API_PREFIX}/gateway/policy/draft`,
    jsonInit("PUT", document),
  );
}

/**
 * Pins a reviewed draft using its expected digest (enforcing two-person rule + step-up).
 * Throws PolicyError with status 409 if the server draft changed concurrently.
 */
export async function pinPolicy(digest: string): Promise<{ ok: boolean }> {
  return requestPolicyJson<{ ok: boolean }>(
    `${API_PREFIX}/gateway/policy/pin`,
    jsonInit("POST", { digest }),
  );
}

/**
 * Commands the gateway process to reload the pinned policy into active memory.
 * Permitted only when the gateway operating mode is 'off' or 'advisory'.
 */
export async function reloadPolicy(): Promise<{ ok: boolean }> {
  return requestPolicyJson<{ ok: boolean }>(
    `${API_PREFIX}/gateway/policy/reload`,
    jsonInit("POST"),
  );
}


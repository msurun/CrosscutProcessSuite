// frontend/src/tuningApi.ts
/**
 * Typed client for the tuning write path (ADR 014): propose, list, approve, reject, roll back.
 * Routes: POST /api/loops/{id}/tuning/proposals and /api/tuning/proposals[...]. Every call goes
 * through apiFetch, so the CSRF header, the 401 event and the 428 step-up retry are shared.
 * Errors carry the HTTP status and the machine code of the server's `detail`.
 */

import { apiFetch } from "./http";

const API_PREFIX = "/api";

export type ConfidenceLevel = "high" | "medium" | "low";
export type TuningMethod = "simc" | "amigo" | "amigo_pid";
export type ReviewVerdict = "insufficient_data" | "worse" | "worse_early" | "improved" | "neutral";

/** One parameter change: old value (`from`) to new value (`to`) in `unit`. */
export interface TuningItem {
  param: "gain" | "ti" | "td" | "tf";
  target: string;
  unit: string;
  from: number;
  to: number;
}

export interface PreviewPair {
  current: number | null;
  proposed: number | null;
}

/** Model-simulated comparison; always a prediction, never a measurement. */
export interface TuningPreview {
  label: string;
  iae_ratio: number;
  overshoot_pct: PreviewPair;
  settling_time_s: PreviewPair;
  ms: PreviewPair;
}

export interface TuningSource {
  method: string;
  robustness: number;
  model?: { K: number; tau_s: number; theta_s: number; process_kind: string };
  window?: { dataset_id?: string; history?: boolean; start: string; end: string };
  step_test_id?: string;
}

/** Why the applied values cannot be trusted: audit_unverified, audit_chain_broken,
 * param_changed_externally (or `true` = unspecified). */
export type AppliedInvalid = boolean | string;

/** The applied block; the values are null when the gateway audit could not confirm them. */
export interface TuningApplied {
  from_read: Record<string, number | null> | null;
  to_read: Record<string, number | null> | null;
  t: string;
  approver: string;
  source?: string; // "audit" or "gateway_reply"
  chain_ok?: boolean;
  invalid?: AppliedInvalid;
}

export interface TuningReview {
  verdict: ReviewVerdict;
  t?: string;
  metrics?: Record<string, number | null>;
  reasons?: string[];
  early?: string;
  before?: Record<string, number | boolean | null>;
  after?: Record<string, number | boolean | null>;
  note?: string;
}

export interface TuningDecision {
  accepted: boolean;
  reason_code: string;
}

/** A parameter write target inside an open write intent. */
export interface ParamIntentTarget {
  target: string;
  to_value: number;
  current_value: number | null;
}

/** An open parameter write intent recorded before write to DCS. */
export interface ParamIntentRecord {
  key: string;
  loop_id: string;
  created_at: string;
  proposer: string;
  targets: ParamIntentTarget[];
}

/** Listing payload from GET /tuning/intents. */
export interface IntentsPayload {
  store_state: "ok" | "damaged";
  intents: ParamIntentRecord[];
}

/** A proposal record as the API shows it (record merged with its review file). */
export interface TuningProposal {
  id: string;
  loop_id: string;
  created_by: string;
  created_at: string;
  expires_at: string;
  vendor_form: { key: string; evidence: string };
  source: TuningSource;
  confidence: { level: ConfidenceLevel; reasons: string[] };
  caveats: string[];
  items: TuningItem[];
  preview: TuningPreview;
  rollback_of: string | null;
  status: string;
  gateway_key: string | null;
  applied: TuningApplied | null;
  review: TuningReview | null;
  rollback_recommended: boolean;
  decision?: TuningDecision;
}

/** Body of POST /loops/{id}/tuning/proposals (exactly one of dataset_id and history). */
export interface ProposeBody {
  vendor_form: string;
  method: TuningMethod;
  reason: string;
  dataset_id?: string;
  history?: { start: string; end: string };
  start_s?: number;
  end_s?: number;
  robustness?: number;
  step_test_id?: string;
}

/** Page size the list uses; the server accepts 1-200 (default 100). */
export const PAGE_SIZE = 100;

/** The list is a plain array (no total): a full page means that more may follow. */
export interface ProposalFilter {
  loopId?: string;
  status?: string;
  limit?: number;
  offset?: number;
}

/** An HTTP failure: `code` is the machine code of the server's detail ("" when it has none). */
export class TuningApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message || code || String(status));
    this.name = "TuningApiError";
    this.status = status;
    this.code = code;
  }
}

interface ErrorParts {
  code: string;
  message: string;
}

/** The code and message of a `detail` that is a string or a {code, message} object. */
function partsOfDetail(detail: unknown): ErrorParts {
  if (typeof detail === "string") return { code: detail, message: detail };
  if (typeof detail === "object" && detail !== null && !Array.isArray(detail)) {
    const { code, message } = detail as { code?: unknown; message?: unknown };
    if (typeof code === "string") return { code, message: typeof message === "string" ? message : code };
  }
  return { code: "", message: "" };
}

async function readParts(response: Response): Promise<ErrorParts> {
  try {
    const body: unknown = await response.json();
    return partsOfDetail((body as { detail?: unknown } | null)?.detail);
  } catch {
    return { code: "", message: "" };
  }
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(url, init);
  if (!response.ok) {
    const { code, message } = await readParts(response);
    throw new TuningApiError(response.status, code, message || response.statusText);
  }
  return (await response.json()) as T;
}

function post(body?: unknown): RequestInit {
  if (body === undefined) return { method: "POST" };
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

const proposalUrl = (id: string): string => `${API_PREFIX}/tuning/proposals/${encodeURIComponent(id)}`;

/** GET /tuning/proposals, newest first, narrowed by loop and status, one page (limit, offset). */
export async function fetchTuningProposals(filter: ProposalFilter = {}): Promise<TuningProposal[]> {
  const query = new URLSearchParams();
  if (filter.loopId) query.set("loop_id", filter.loopId);
  if (filter.status) query.set("status", filter.status);
  if (filter.limit !== undefined) query.set("limit", String(filter.limit));
  if (filter.offset !== undefined) query.set("offset", String(filter.offset));
  const text = query.toString();
  return requestJson<TuningProposal[]>(`${API_PREFIX}/tuning/proposals${text ? `?${text}` : ""}`);
}

/** GET /tuning/proposals/{id}. */
export async function fetchTuningProposal(id: string): Promise<TuningProposal> {
  return requestJson<TuningProposal>(proposalUrl(id));
}

/** POST /loops/{loopId}/tuning/proposals (permission gw.propose). */
export async function createTuningProposal(loopId: string, body: ProposeBody): Promise<TuningProposal> {
  const url = `${API_PREFIX}/loops/${encodeURIComponent(loopId)}/tuning/proposals`;
  return requestJson<TuningProposal>(url, post(body));
}

/** POST /tuning/proposals/{id}/approve (permission gw.approve.tuning, a second person). */
export async function approveTuningProposal(id: string): Promise<TuningProposal> {
  return requestJson<TuningProposal>(`${proposalUrl(id)}/approve`, post());
}

/** POST /tuning/proposals/{id}/reject (permission gw.reject). */
export async function rejectTuningProposal(id: string): Promise<TuningProposal> {
  return requestJson<TuningProposal>(`${proposalUrl(id)}/reject`, post());
}

/** POST /tuning/proposals/{id}/rollback (permission gw.propose; applied or reviewed records). */
export async function rollbackTuningProposal(id: string, reason?: string): Promise<TuningProposal> {
  const body = reason === undefined ? undefined : { reason };
  return requestJson<TuningProposal>(`${proposalUrl(id)}/rollback`, post(body));
}

/** GET /tuning/intents, optionally narrowed by loop_id. */
export async function fetchOpenIntents(loopId?: string): Promise<IntentsPayload> {
  const query = loopId ? `?loop_id=${encodeURIComponent(loopId)}` : "";
  return requestJson<IntentsPayload>(`${API_PREFIX}/tuning/intents${query}`);
}

/** POST /tuning/intents/{key}/resolve (requires gw.approve.tuning plus step-up). */
export async function resolveOpenIntent(key: string): Promise<Record<string, unknown>> {
  const url = `${API_PREFIX}/tuning/intents/${encodeURIComponent(key)}/resolve`;
  return requestJson<Record<string, unknown>>(url, post());
}

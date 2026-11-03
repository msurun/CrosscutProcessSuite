// frontend/src/gatewayApi.ts
/**
 * Typed client for Write Gateway management routes (URL prefix /api/gateway).
 * Supports status monitoring, pending proposal approvals, mode configuration,
 * target re-enabling, emergency shutdown, and audit log queries.
 */

export type GatewayMode = "off" | "advisory" | "dry_run" | "confirm" | "supervised";

export type GatewayTargetState =
  | "enabled"
  | "hold_off"
  | "stopped:rejected"
  | "stopped:comm"
  | "stopped:readback"
  | "killed"
  | string;

export interface GatewayStatus {
  mode: GatewayMode | string;
  targets: Record<string, GatewayTargetState>;
  pending: number;
}

export interface GatewayProposal {
  key: string;
  target_tag: string;
  value: number;
  proposer: string;
  t_ns: number;
  reason: string;
}

export interface GatewayDecision {
  accepted: boolean;
  reason_code: string;
  clamped_value: number | null;
}

export interface GatewayAuditRecord {
  seq: string;
  t_ns: string;
  event: string;
  prev_hash: string;
  hash: string;
  tag?: string;
  value?: string;
  proposer?: string;
  mode?: string;
  reason_code?: string;
  [key: string]: string | undefined;
}

export interface GatewayAuditResponse {
  records: GatewayAuditRecord[];
  chain_ok: boolean;
}

export interface GatewayActionResponse {
  ok: boolean;
  mode?: string;
}

export class GatewayApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "GatewayApiError";
    this.status = status;
  }
}

const API_PREFIX = "/api";

async function readDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
    }
  } catch {
    // Body was not JSON; fallback to statusText
  }
  return response.statusText;
}

async function requestJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) {
    const message = await readDetail(response);
    throw new GatewayApiError(response.status, message);
  }
  return (await response.json()) as T;
}

function jsonPostOptions(body?: unknown): RequestInit {
  if (body === undefined) return { method: "POST" };
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export async function fetchGatewayStatus(): Promise<GatewayStatus> {
  return requestJson<GatewayStatus>(`${API_PREFIX}/gateway/status`);
}

export async function fetchGatewayPending(): Promise<GatewayProposal[]> {
  return requestJson<GatewayProposal[]>(`${API_PREFIX}/gateway/pending`);
}

export async function approveProposal(key: string): Promise<GatewayDecision> {
  const encoded = encodeURIComponent(key);
  return requestJson<GatewayDecision>(`${API_PREFIX}/gateway/pending/${encoded}/approve`, jsonPostOptions());
}

export async function rejectProposal(key: string): Promise<GatewayActionResponse> {
  const encoded = encodeURIComponent(key);
  return requestJson<GatewayActionResponse>(`${API_PREFIX}/gateway/pending/${encoded}/reject`, jsonPostOptions());
}

export async function killGateway(): Promise<GatewayActionResponse> {
  return requestJson<GatewayActionResponse>(`${API_PREFIX}/gateway/kill`, jsonPostOptions());
}

export async function reEnableTarget(tag: string): Promise<GatewayActionResponse> {
  const encoded = encodeURIComponent(tag);
  return requestJson<GatewayActionResponse>(`${API_PREFIX}/gateway/targets/${encoded}/re-enable`, jsonPostOptions());
}

export async function setGatewayMode(mode: string): Promise<GatewayActionResponse> {
  return requestJson<GatewayActionResponse>(`${API_PREFIX}/gateway/mode`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
}

export async function fetchGatewayAudit(limit = 200): Promise<GatewayAuditResponse> {
  return requestJson<GatewayAuditResponse>(`${API_PREFIX}/gateway/audit?limit=${limit}`);
}


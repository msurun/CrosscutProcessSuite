// frontend/src/controllersApi.ts
/**
 * Typed client of the APC core operator console: list, detail, command, variable override.
 * Routes: GET /api/controllers[/{id}], POST /api/controllers/{id}/command and
 * PUT /api/controllers/{id}/variables/{vid}. Calls go through apiFetch (CSRF, 401, step-up).
 * A failure throws ControllersApiError with the status and the server's problems as text lines.
 */

import { apiFetch } from "./http";

const API_PREFIX = "/api/controllers";

export type ControllerCommand = "switch_on" | "switch_off" | "standby";
export type ControllerState = "off" | "standby" | "on" | "advisory" | "shed";

export interface Bounds {
  lo: number;
  hi: number;
}

/** One row of GET /controllers: the host's last record plus the disabled variable ids. */
export interface ControllerSummary {
  id: string;
  type: string;
  description: string;
  cycle_s: number;
  state: ControllerState;
  reason: string;
  last_cycle_utc: string | null;
  last_duration_s: number | null;
  overruns: number;
  consecutive_overruns: number;
  liveness_utc: string | null;
  last_explanation: string;
  /** Moves the controller would make in the advisory state (never proposed). */
  last_advice: { variable_id: string; target_tag: string; value: number; reason: string }[] | null;
  warnings: string[] | null;
  disabled: string[];
}

export interface VariableLimits {
  eng?: Bounds;
  operator?: Bounds;
  validity?: Bounds;
  move_max?: number;
  rate_max?: number;
  /** The operator range of the catalogue, before any operator override. */
  operator_catalogue: Bounds | null;
}

export interface ControllerVariable {
  id: string;
  role: "MV" | "CV" | "DV" | "ICV";
  binding: { loop?: string; tag?: string };
  enabled: boolean;
  limits: VariableLimits;
  status: "good" | "uncertain" | "bad" | null;
  reasons: string[];
  value: number | null;
  sp_value: number | null;
  source_utc: string | null;
}

export interface ControllerDetail extends ControllerSummary {
  variables: ControllerVariable[];
}

/** An HTTP failure; `problems` holds the server's detail as one or more readable lines. */
export class ControllersApiError extends Error {
  readonly status: number;
  readonly problems: string[];

  constructor(status: number, problems: string[]) {
    super(problems.join("; ") || String(status));
    this.name = "ControllersApiError";
    this.status = status;
    this.problems = problems;
  }
}

/** The lines of a FastAPI `detail`: a string, a list of strings or a list of {msg} objects. */
function linesOf(detail: unknown): string[] {
  if (typeof detail === "string") return [detail];
  if (!Array.isArray(detail)) return [];
  return detail.map((one) => (typeof one === "string" ? one : String((one as { msg?: unknown }).msg ?? "")));
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(url, init);
  if (!response.ok) {
    let detail: unknown = null;
    try {
      detail = ((await response.json()) as { detail?: unknown } | null)?.detail;
    } catch {
      detail = null;
    }
    const lines = linesOf(detail);
    throw new ControllersApiError(response.status, lines.length > 0 ? lines : [response.statusText]);
  }
  return (await response.json()) as T;
}

function send(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

/** GET /controllers. */
export async function fetchControllers(): Promise<ControllerSummary[]> {
  const body = await requestJson<{ controllers: ControllerSummary[] }>(API_PREFIX);
  return body.controllers;
}

/** GET /controllers/{id}. */
export async function fetchController(id: string): Promise<ControllerDetail> {
  return requestJson<ControllerDetail>(`${API_PREFIX}/${encodeURIComponent(id)}`);
}

/** POST /controllers/{id}/command (permission ctl.operate; switching off never needs a step-up). */
export async function sendControllerCommand(id: string, command: ControllerCommand): Promise<void> {
  await requestJson<unknown>(`${API_PREFIX}/${encodeURIComponent(id)}/command`, send("POST", { command }));
}

/** What the operator sets on one variable: on/off and, optionally, an operator range. */
export interface VariableOverride {
  enabled: boolean;
  operator?: Bounds;
}

/** PUT /controllers/{id}/variables/{vid}: answers the refreshed controller detail. */
export async function putControllerVariable(
  id: string,
  variableId: string,
  override: VariableOverride,
): Promise<ControllerDetail> {
  const url = `${API_PREFIX}/${encodeURIComponent(id)}/variables/${encodeURIComponent(variableId)}`;
  return requestJson<ControllerDetail>(url, send("PUT", override));
}

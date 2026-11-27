// Typed client and pure helpers of the soft sensor Runtime panel: the runtime state of one sensor
// (mode, latest output, last lab residual, failover events, deploy gate) and the mode change.
// No React, so the helpers are unit-tested alone. A refused mode change is HTTP 409 with the text in `detail`.
import { API_PREFIX, ApiError, getJson, sendJson } from "./api";
import { formatFixed } from "./format";

export type RuntimeMode = "off" | "shadow" | "backup" | "primary";
export type RuntimeStatus = "good" | "uncertain" | "bad";
export type RuntimeSource = "instrument" | "softsensor";

/** The modes offered in the select, in the order shown. */
export const RUNTIME_MODES: readonly RuntimeMode[] = ["shadow", "backup", "primary", "off"];

export interface RuntimeOutput {
  t_utc: string;
  value: number | null;
  status: RuntimeStatus;
  reason: string;
  source: RuntimeSource | "none";
  used_downstream: boolean;
  estimate: number | null;
  bias: number | null;
  drift: boolean;
  effective_mode: string;
}

export interface RuntimeLab {
  sample_utc: string;
  lab: number;
  estimate: number;
  residual: number;
}

export interface RuntimeEvent {
  t_utc: string;
  from: RuntimeSource;
  to: RuntimeSource;
  reason: string;
}

export interface RuntimeGate {
  available: boolean;
  deploy: boolean;
  skill: number | null;
  reasons: string[];
  message: string;
}

export interface SoftSensorRuntime {
  sensor_id: string;
  mode: RuntimeMode;
  changed_by: string | null;
  changed_utc: string | null;
  output: RuntimeOutput | null;
  last_lab: RuntimeLab | null;
  events: RuntimeEvent[];
  gate: RuntimeGate;
}

const runtimeUrl = (sid: string): string => `${API_PREFIX}/softsensor/${encodeURIComponent(sid)}`;

/** GET the runtime state of sensor `sid`. */
export async function fetchSoftSensorRuntime(sid: string): Promise<SoftSensorRuntime> {
  return getJson<SoftSensorRuntime>(`${runtimeUrl(sid)}/runtime`);
}

/** PUT a new mode; resolves with the new runtime state, rejects with an ApiError (409 = refused). */
export async function setSoftSensorMode(sid: string, mode: RuntimeMode): Promise<SoftSensorRuntime> {
  return sendJson<SoftSensorRuntime>("PUT", `${runtimeUrl(sid)}/mode`, { mode });
}

/** The text of a failed mode change: the exact server detail (409 refusal or 422), else the error message. */
export function modeErrorText(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : String(error);
}

/** True when applying `selected` would change anything. */
export function canApplyMode(current: RuntimeMode, selected: RuntimeMode, busy: boolean): boolean {
  return !busy && selected !== current;
}

/** Plain-text marker of a status (shown with the badge so the status never relies on colour alone). */
export function statusMarker(status: RuntimeStatus): string {
  return { good: "[OK]", uncertain: "[?]", bad: "[X]" }[status];
}

/** CSS modifier of the status chip. */
export function statusClass(status: RuntimeStatus): string {
  return { good: "status-chip--ok", uncertain: "status-chip--warning", bad: "status-chip--problem" }[status];
}

/** Value text with `decimals` decimals, or "--" for a missing value. */
export function valueText(value: number | null, decimals = 3): string {
  return value === null || !Number.isFinite(value) ? "--" : formatFixed(value, decimals);
}

/** Events newest first (ISO UTC strings sort as text); the input is not changed. */
export function eventsNewestFirst(events: readonly RuntimeEvent[]): RuntimeEvent[] {
  return [...events].sort((a, b) => b.t_utc.localeCompare(a.t_utc));
}

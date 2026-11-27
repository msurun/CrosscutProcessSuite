// frontend/src/healthApi.ts
/**
 * Typed client of the Administration > Health page (#170): GET /api/admin/health (read-only) and
 * GET /api/admin/logs/export (a zip of the application logs of a time range; needs users.manage).
 * Calls go through apiFetch (401 handling); a failure throws HealthApiError with the server detail.
 */

import { apiFetch } from "./http";

const API_PREFIX = "/api/admin";

export type HealthStatus = "ok" | "warning" | "error";

/** Machine-readable extras of an item; which keys exist depends on the item. */
export interface HealthDetails {
  uptime_s?: number | null;
  age_s?: number | null;
  updated_age_s?: number | null;
  lag_s?: number | null;
  period_s?: number | null;
  overrun_count?: number;
  last_run_utc?: string | null;
  last_success_utc?: string | null;
  last_error_utc?: string | null;
  last_error?: string | null;
  last_write_utc?: string | null;
  mode?: string | null;
  free_bytes?: number;
  total_bytes?: number;
  versions?: Record<string, string | null>;
}

/** One checked thing: id like "runtime", "job:j1", "liveness:controller:C1", "disk". */
export interface HealthItem {
  id: string;
  group: "runtime" | "jobs" | "gateway" | "liveness" | "audit" | "system";
  status: HealthStatus;
  code: string;
  reason: string;
  details: HealthDetails;
}

/** Payload of GET /admin/health; `status` is the worst item status. */
export interface HealthReport {
  generated_utc: string;
  status: HealthStatus;
  items: HealthItem[];
}

export class HealthApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "HealthApiError";
    this.status = status;
  }
}

async function failure(response: Response): Promise<HealthApiError> {
  let detail = response.statusText;
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") detail = body.detail;
  } catch {
    // keep the status text
  }
  return new HealthApiError(response.status, detail);
}

/** Read the health report. @throws {HealthApiError} on a non-2xx answer. */
export async function fetchHealth(): Promise<HealthReport> {
  const response = await apiFetch(`${API_PREFIX}/health`);
  if (!response.ok) throw await failure(response);
  return (await response.json()) as HealthReport;
}

/** URL of the log export of an ISO time range (both ends are optional: the server defaults to 24 h). */
export function logExportUrl(startIso: string, endIso: string): string {
  const query = new URLSearchParams();
  if (startIso !== "") query.set("start", startIso);
  if (endIso !== "") query.set("end", endIso);
  const text = query.toString();
  return `${API_PREFIX}/logs/export${text === "" ? "" : `?${text}`}`;
}

/** Download the zip of the logs of the range. @throws {HealthApiError} 403 without users.manage, 422 for a bad range. */
export async function fetchLogExport(startIso: string, endIso: string): Promise<Blob> {
  const response = await apiFetch(logExportUrl(startIso, endIso));
  if (!response.ok) throw await failure(response);
  return response.blob();
}

/** Save `blob` through a temporary link, the way browsers download a generated file. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

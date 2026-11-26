// Typed client for the backup and restore routes (issue #167): download, dry run, restore.
// The archive travels as the raw request body; step-up (428) is handled by apiFetch.
import { API_PREFIX, ApiError } from "./api";
import { apiFetch } from "./http";

/** One planned change of a restore. */
export interface BackupChange {
  path: string;
  action: "add" | "replace" | "remove" | "unchanged" | "keep_evidence";
}

/** A secret the restored site needs again (never part of the archive). */
export interface MustReenter {
  kind: "gateway_key" | "source_secret";
  source?: string;
  ref?: string;
  where?: string;
}

/** The dry-run report of an uploaded archive. */
export interface BackupReport {
  ok: boolean;
  archive_sha256: string;
  problems: string[];
  created_utc: string;
  format_version: number;
  changes: BackupChange[];
  must_reenter: MustReenter[];
}

const BASE = `${API_PREFIX}/admin/backup`;

/** The error of a failed response: a string detail, a list of problems joined by line, or the status text. */
async function failure(response: Response): Promise<ApiError> {
  let message = response.statusText;
  try {
    const detail = ((await response.json()) as { detail?: unknown }).detail;
    if (typeof detail === "string") message = detail;
    else if (Array.isArray(detail)) message = detail.map(String).join("\n");
  } catch {
    // Not JSON: keep the status text.
  }
  return new ApiError(response.status, message);
}

/** Download the backup zip; the file name comes from the Content-Disposition header. */
export async function downloadBackup(): Promise<{ blob: Blob; filename: string }> {
  const response = await apiFetch(BASE);
  if (!response.ok) throw await failure(response);
  const header = response.headers.get("Content-Disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(header)?.[1] ?? "crosscut-backup.zip";
  return { blob: await response.blob(), filename };
}

async function post(url: string, file: Blob): Promise<Response> {
  const response = await apiFetch(url, { method: "POST", body: file, headers: { "Content-Type": "application/zip" } });
  if (!response.ok) throw await failure(response);
  return response;
}

/** Dry run: validate the archive and list what a restore would change. Nothing is changed. */
export async function inspectBackup(file: Blob): Promise<BackupReport> {
  return (await (await post(`${BASE}/inspect`, file)).json()) as BackupReport;
}

/** Restore the archive that was inspected; `sha256` is the report's `archive_sha256`. */
export async function restoreBackup(file: Blob, sha256: string): Promise<BackupReport> {
  return (await (await post(`${BASE}/restore?confirm=${encodeURIComponent(sha256)}`, file)).json()) as BackupReport;
}

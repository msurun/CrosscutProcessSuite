// Typed client for the source management routes (issue #208): save, delete, test and secret.
// Reuses getJson/sendJson/ApiError from api.ts; a 428 step-up on the secret route is retried by apiFetch.
import { API_PREFIX, ApiError, getJson, sendJson } from "./api";
import { apiFetch } from "./http";

export type SourceDriver = "opcua" | "pi" | "piwebapi" | "sql" | "csv";
export type AuthKind = "basic" | "kerberos" | "bearer";

/** A source entry of site.json; it never holds a password or token. */
export interface SourceEntry {
  id: string;
  driver: SourceDriver;
  endpoint?: string;
  base_url?: string;
  data_server?: string;
  web_id?: string;
  profile?: string;
  auth?: { kind: AuthKind; credential_env?: string; credential_ref?: string };
}

/** What a test of a source reports. */
export interface SourceTestReport {
  status: string;
  capabilities: string[];
}

/** Raised by {@link deleteSource} when catalogue tags still read from the source (HTTP 409). */
export class SourceInUseError extends ApiError {
  readonly tags: string[];

  constructor(tags: string[]) {
    super(409, "source_in_use", { code: "source_in_use" });
    this.tags = tags;
  }
}

const base = (id: string): string => `${API_PREFIX}/sources/${encodeURIComponent(id)}`;

/** List the configured sources with their full entries. */
export async function listSourceEntries(): Promise<{ sources: SourceEntry[] }> {
  return getJson<{ sources: SourceEntry[] }>(`${API_PREFIX}/sources`);
}

/** Add or replace a source; a 422 ApiError message lists the problems, one per line. */
export async function saveSource(entry: SourceEntry): Promise<SourceEntry & { secret_stored: boolean }> {
  const { id, ...body } = entry;
  return sendJson("PUT", base(id), body);
}

/** Delete a source; throws {@link SourceInUseError} with the tag ids when it is still used. */
export async function deleteSource(id: string): Promise<void> {
  const response = await apiFetch(base(id), { method: "DELETE" });
  if (response.ok) return;
  const body = (await response.json().catch(() => ({}))) as { detail?: { code?: string; tags?: unknown } | string };
  const detail = body.detail;
  if (response.status === 409 && typeof detail === "object" && detail?.code === "source_in_use") {
    throw new SourceInUseError(Array.isArray(detail.tags) ? detail.tags.map(String) : []);
  }
  throw new ApiError(response.status, typeof detail === "string" ? detail : response.statusText);
}

/** Whether a secret is stored for the source; the value is never returned. */
export async function fetchSecretStored(id: string): Promise<boolean> {
  return (await getJson<{ stored: boolean }>(`${base(id)}/secret`)).stored;
}

/** Store the secret (needs a fresh step-up; the shared fetch asks for it and retries). */
export async function putSecret(id: string, value: string): Promise<void> {
  await sendJson("PUT", `${base(id)}/secret`, { value });
}

/** Forget the stored secret. */
export async function deleteSecret(id: string): Promise<void> {
  const response = await apiFetch(`${base(id)}/secret`, { method: "DELETE" });
  if (!response.ok) throw new ApiError(response.status, response.statusText);
}

/** Try an unsaved source entry (including its id). */
export async function testDraft(entry: SourceEntry): Promise<SourceTestReport> {
  return sendJson("POST", `${API_PREFIX}/sources/test-draft`, entry);
}

/** Test a saved source. */
export async function testSavedSource(id: string): Promise<SourceTestReport> {
  return sendJson("POST", `${base(id)}/test`, {});
}

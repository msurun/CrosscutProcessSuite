// frontend/src/dependenciesApi.ts
/**
 * Typed client of the dependency tracking routes (#166): GET /api/dependencies lists the configs, models
 * and jobs that no longer match the published catalogue; POST /api/dependencies/confirm accepts the
 * catalogue for one of them (an audited engineer decision, a note is required).
 */
import { API_PREFIX, ApiError } from "./api";
import { apiFetch } from "./http";

/** What changed on a tag a dependent was built on. */
export type ReasonKind = "removed" | "remapped" | "unit_changed" | "role_moved" | "range_changed" | "rebound";

/** The action the console offers for a stale dependent. */
export type DependencyAction = "relearn" | "reconfirm" | "edit_config";

export interface DependencyReason {
  tag: string;
  kind: ReasonKind;
  detail: string;
}

/** One stale dependent: a job, an anomaly or soft sensor model, or an identified model. */
export interface StaleDependency {
  key: string;
  kind: "job" | "anomaly" | "softsensor" | "ident_model";
  id: string;
  reasons: DependencyReason[];
  built_on_version: number | null;
  stale_since_version: number | null;
  needs_relearn: boolean;
  actions: DependencyAction[];
}

export interface DependencyList {
  published_version: number | null;
  tracked: number;
  items: StaleDependency[];
}

const BASE = `${API_PREFIX}/dependencies`;

async function failure(response: Response): Promise<ApiError> {
  let message = response.statusText;
  try {
    const detail = ((await response.json()) as { detail?: unknown }).detail;
    if (typeof detail === "string") message = detail;
  } catch {
    // Not JSON: keep the status text.
  }
  return new ApiError(response.status, message);
}

/** The stale dependents of the published catalogue. */
export async function fetchDependencies(): Promise<DependencyList> {
  const response = await apiFetch(BASE);
  if (!response.ok) throw await failure(response);
  return (await response.json()) as DependencyList;
}

/** Accept the catalogue as it is for one dependent; `note` says why (required, audited). */
export async function confirmDependency(key: string, note: string): Promise<void> {
  const response = await apiFetch(`${BASE}/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key, note }),
  });
  if (!response.ok) throw await failure(response);
}

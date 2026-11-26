// Client for the plant-history sources: the source list, the site catalogue tags and the cached history load.
// Used by the SourcePicker; reuses getJson/ApiError from api.ts so errors look like every other call.
import { API_PREFIX, ApiError, getJson } from "./api";

/** One configured data source (`GET /api/sources`). */
export interface SiteSource {
  id: string;
  driver: string;
  endpoint?: string;
  description?: string;
}

/** One tag of the site catalogue; `source` names the SiteSource that serves it. */
export interface CatalogueTag {
  id: string;
  name?: string;
  description?: string;
  unit?: string;
  source?: string;
  address?: string;
}

/** Result of a history load: the cached dataset the rest of the UI can open. */
export interface HistoryResult {
  dataset_id: string;
  cached: boolean;
  time_range: { start_utc: string; end_utc: string };
  tags: string[];
}

/** List the configured sources. @throws {ApiError} On a non-2xx response. */
export async function listSources(): Promise<{ sources: SiteSource[] }> {
  return getJson<{ sources: SiteSource[] }>(`${API_PREFIX}/sources`);
}

/** Catalogue tags of the site document; 404 means no catalogue yet, which is an empty list, not an error. */
export async function fetchSiteTags(): Promise<CatalogueTag[]> {
  try {
    const site = await getJson<{ tags?: CatalogueTag[] }>(`${API_PREFIX}/site`);
    return site.tags ?? [];
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return [];
    throw error;
  }
}

/**
 * Load plant history of `tags` over a UTC range from a source into a cached dataset.
 * @param range ISO UTC bounds of the window.
 * @param periodS Optional resampling period in seconds; omitted means raw samples.
 */
export async function loadHistory(
  sourceId: string,
  tags: readonly string[],
  range: { start_utc: string; end_utc: string },
  periodS?: number,
): Promise<HistoryResult> {
  const query = new URLSearchParams();
  for (const tag of tags) query.append("tag", tag);
  query.set("start", range.start_utc);
  query.set("end", range.end_utc);
  if (periodS !== undefined) query.set("period_s", String(periodS));
  return getJson<HistoryResult>(`${API_PREFIX}/sources/${encodeURIComponent(sourceId)}/history?${query.toString()}`);
}

/** What a history load asked for; carried in the URL so a shared link can repeat it (#202). */
export interface HistoryRequest {
  source: string;
  tags: string[];
  start_utc: string;
  end_utc: string;
  period_s?: number;
}

/** The route query of a request: `src`, `tags` (comma list), `start`, `end` and `period` when set. */
export function historyQuery(request: HistoryRequest): Record<string, string> {
  const query: Record<string, string> = {
    src: request.source,
    tags: request.tags.join(","),
    start: request.start_utc,
    end: request.end_utc,
  };
  if (request.period_s) query.period = String(request.period_s);
  return query;
}

/** The request a route query describes, or null when `src`, `tags`, `start` or `end` is missing. */
export function parseHistoryQuery(query: Record<string, string> | undefined): HistoryRequest | null {
  if (!query?.src || !query.tags || !query.start || !query.end) return null;
  const period = Number(query.period);
  return {
    source: query.src,
    tags: query.tags.split(",").filter((tag) => tag !== ""),
    start_utc: query.start,
    end_utc: query.end,
    period_s: period > 0 ? period : undefined,
  };
}

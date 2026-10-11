/**
 * Typed client for the dataset API (FastAPI, URL prefix `/api`).
 *
 * All timestamps are UTC nanoseconds. Numbers may be null when a bucket has no samples.
 */

/** One dataset as listed by `GET /api/datasets`. */
export interface DatasetSummary {
  id: string;
  source: Record<string, unknown>;
  time_range: { start_utc: string; end_utc: string };
  n_tags: number;
  n_samples: number;
}

/** Metadata of a single tag inside a dataset. */
export interface TagInfo {
  id: string;
  unit?: string;
  description?: string;
  kind?: string;
}

/** One downsampled series: `t`, `min`, `max` and `mean` share the same length. */
export interface Series {
  tag: string;
  downsampled: boolean;
  t: number[];
  min: (number | null)[];
  max: (number | null)[];
  mean: (number | null)[];
}

/** Payload of `GET /api/datasets/{id}/series`. */
export interface SeriesResponse {
  dataset_id: string;
  series: Series[];
}

/** Error raised for any non-2xx response; `status` is the HTTP status code. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

/** Options for {@link fetchSeries}; an omitted bound is sent as no query parameter. */
export interface FetchSeriesOptions {
  startNs?: number;
  endNs?: number;
  maxPoints?: number;
}

const API_PREFIX = '/api';
/** Name of the field FastAPI puts its error message in. */
const DETAIL_FIELD = 'detail';

/**
 * Read the error message out of a failed response body.
 * Returns the `detail` field when the body is JSON with a string detail, the status text otherwise.
 */
async function readErrorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (isRecordWithStringDetail(body)) {
      return body.detail;
    }
  } catch {
    // Body was empty or not JSON: fall through to the status text.
  }
  return response.statusText;
}

/** True when `value` is an object with a string `detail` property. */
function isRecordWithStringDetail(value: unknown): value is Record<'detail', string> {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const detail = (value as Record<string, unknown>)[DETAIL_FIELD];
  return typeof detail === 'string';
}

/**
 * Fetch `url` and parse the JSON body.
 * @throws {ApiError} When the response status is not ok, with the server `detail` as message.
 */
async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response));
  }
  return (await response.json()) as T;
}

/**
 * List every dataset the backend knows about.
 * @returns The dataset summaries, in the order the backend returned them.
 * @throws {ApiError} On a non-2xx response.
 */
export async function fetchDatasets(): Promise<DatasetSummary[]> {
  return getJson<DatasetSummary[]>(`${API_PREFIX}/datasets`);
}

/**
 * List the tags of one dataset.
 * @param datasetId Identifier returned by {@link fetchDatasets}.
 * @throws {ApiError} On a non-2xx response, for example when the dataset does not exist.
 */
export async function fetchTags(datasetId: string): Promise<TagInfo[]> {
  const id = encodeURIComponent(datasetId);
  return getJson<TagInfo[]>(`${API_PREFIX}/datasets/${id}/tags`);
}

/**
 * Read one or more tag series, optionally limited to a time range and a point budget.
 * @param tags Tag ids to retrieve; repeated as one `tag` query parameter per value.
 * @param options Time range in UTC nanoseconds and maximum points per series; omitted keys are not sent.
 * @throws {ApiError} On a non-2xx response, for example when a tag is unknown.
 */
export async function fetchSeries(
  datasetId: string,
  tags: readonly string[],
  options: FetchSeriesOptions = {},
): Promise<SeriesResponse> {
  const id = encodeURIComponent(datasetId);
  const query = new URLSearchParams();
  for (const tag of tags) {
    query.append('tag', tag);
  }
  appendOptionalInt(query, 'start', options.startNs);
  appendOptionalInt(query, 'end', options.endNs);
  appendOptionalInt(query, 'max_points', options.maxPoints);
  return getJson<SeriesResponse>(`${API_PREFIX}/datasets/${id}/series?${query.toString()}`);
}

/** Append `name=value` when `value` is defined, so the backend keeps its own default. */
function appendOptionalInt(query: URLSearchParams, name: string, value: number | undefined): void {
  if (value !== undefined) {
    query.append(name, String(value));
  }
}

/** Status level of a loop, as decided by the backend (see `docs/design/screens.md`). */
export type LoopStatus = "ok" | "warning" | "problem" | "unused";

/** One finding as a stable code plus numeric parameters; the UI turns it into a sentence. */
export interface LoopFinding {
  code: string;
  params: Record<string, number>;
}

/** Analysis result of one control loop (`GET /api/datasets/{id}/loops`). */
export interface LoopSummary {
  name: string;
  pv: string;
  sp: string;
  out: string;
  mode: string;
  unit: string;
  status: LoopStatus;
  health_percent: number | null;
  classification: string;
  findings: LoopFinding[];
  service_percent: number;
  saturation_percent: number;
  harris_index: number | null;
  oscillation_period_s: number | null;
  stiction_verdict: string;
  sparkline: (number | null)[];
}

/** Fetch the loop analysis of a dataset. */
export async function fetchLoops(datasetId: string): Promise<LoopSummary[]> {
  const body = await getJson<{ loops: LoopSummary[] }>(`/api/datasets/${encodeURIComponent(datasetId)}/loops`);
  return body.loops;
}

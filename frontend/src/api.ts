/**
 * Typed client for the dataset API (FastAPI, URL prefix `/api`).
 *
 * All timestamps are UTC nanoseconds. Numbers may be null when a bucket has no samples.
 */

import type { FuzzyDocument } from "./fuzzy";

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

/** A window of the dataset, in seconds since its first sample. */
export interface TimeWindow {
  start_s: number;
  end_s: number;
}

/** Result of `GET /api/datasets/{id}/loops/{loop}/tuning`; texts are codes the UI translates. */
export interface TuningPayload {
  loop: string;
  windows: TimeWindow[];
  window: TimeWindow & { manual_percent: number };
  warnings: string[];
  robustness: number;
  blocked_code: "stiction" | "model_failed" | "poor_fit" | null;
  markdown: string;
  model: { gain: number; time_constant_s: number; delay_s: number } | null;
  fit: { verdict: "good" | "fair" | "poor"; r_squared: number } | null;
  check: { t_s: number[]; measured: (number | null)[]; simulated: (number | null)[] } | null;
  settings: { simc: { kc: number; ti_s: number }; amigo: { kc: number; ti_s: number } } | null;
  dcs_forms: Record<string, Record<string, number>>;
  step?: { t_s: number[]; pv: number[]; out: number[] };
}

/** Identify a loop on a data window and get proposed PI settings (nothing is written to the plant). */
export async function fetchTuning(
  datasetId: string,
  loopName: string,
  options?: { startS?: number; endS?: number; robustness?: number },
): Promise<TuningPayload> {
  const query = new URLSearchParams();
  if (options?.startS !== undefined) query.set("start_s", String(options.startS));
  if (options?.endS !== undefined) query.set("end_s", String(options.endS));
  if (options?.robustness !== undefined) query.set("robustness", String(options.robustness));
  const base = `/api/datasets/${encodeURIComponent(datasetId)}/loops/${encodeURIComponent(loopName)}/tuning`;
  return getJson<TuningPayload>(`${base}?${query.toString()}`);
}

/** Assumptions the user can change on the benefit screen (all optional; the server fills defaults). */
export interface BenefitInputs {
  limit?: number;
  side?: "upper" | "lower";
  valuePerUnitH?: number;
  marginSigmas?: number;
  stdReduction?: number;
}

/** Result of `GET /api/datasets/{id}/loops/{loop}/benefit`; notes are codes the UI translates. */
export interface BenefitPayload {
  loop: string;
  unit: string;
  assumptions: {
    limit: number;
    limit_is_default: boolean;
    side: "upper" | "lower";
    value_per_unit_h: number;
    margin_sigmas: number;
    std_reduction: number;
  };
  estimate: {
    mean: number;
    std_now: number;
    std_target: number;
    current_gap: number;
    shift: number;
    value_per_h: number;
    n_samples_used: number;
  };
  notes: string[];
  curves: { x: number[]; now: number[]; after: number[] };
  markdown: string;
}

/** Estimate what lower PV variability is worth (an estimate from assumptions, not a promise). */
export async function fetchBenefit(
  datasetId: string,
  loopName: string,
  inputs?: BenefitInputs,
): Promise<BenefitPayload> {
  const query = new URLSearchParams();
  if (inputs?.limit !== undefined) query.set("limit", String(inputs.limit));
  if (inputs?.side !== undefined) query.set("side", inputs.side);
  if (inputs?.valuePerUnitH !== undefined) query.set("value_per_unit_h", String(inputs.valuePerUnitH));
  if (inputs?.marginSigmas !== undefined) query.set("margin_sigmas", String(inputs.marginSigmas));
  if (inputs?.stdReduction !== undefined) query.set("std_reduction", String(inputs.stdReduction));
  const base = `/api/datasets/${encodeURIComponent(datasetId)}/loops/${encodeURIComponent(loopName)}/benefit`;
  return getJson<BenefitPayload>(`${base}?${query.toString()}`);
}

/** A rule base in the library: bundled example or the user's own saved copy. */
export interface FuzzySystemInfo {
  id: string;
  name: string;
  source: "example" | "user";
}

/** Result of one what-if evaluation (`POST /api/fuzzy/infer`). */
export interface FuzzyInference {
  inputs: Record<string, number>;
  degrees: Record<string, Record<string, number>>;
  firing: Record<string, number>;
  dominant: string[];
  outputs: Record<string, { crisp: number | null; universe: number[]; aggregated: number[] }>;
}

/** Result of a replay over recorded data; `t` is in UTC nanoseconds, missing values are null. */
export interface FuzzyReplay {
  t: number[];
  inputs: Record<string, (number | null)[]>;
  outputs: Record<string, (number | null)[]>;
  actual: Record<string, (number | null)[]>;
}

async function sendJson<T>(method: string, url: string, body: unknown): Promise<T> {
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const detail = (await response.json()) as { detail?: unknown };
      if (typeof detail.detail === "string") message = detail.detail;
    } catch {
      // keep the status text
    }
    throw new ApiError(response.status, message);
  }
  return (await response.json()) as T;
}

/** The bundled examples and the user's saved rule bases. */
export async function fetchFuzzySystems(): Promise<FuzzySystemInfo[]> {
  return getJson<FuzzySystemInfo[]>("/api/fuzzy");
}

/** One rule base document. */
export async function fetchFuzzySystem(systemId: string): Promise<FuzzyDocument> {
  return getJson<FuzzyDocument>(`/api/fuzzy/${encodeURIComponent(systemId)}`);
}

/** Save a rule base as the user's own (configuration only; nothing is written to a plant). */
export async function saveFuzzySystem(systemId: string, document: FuzzyDocument): Promise<FuzzyDocument> {
  return sendJson<FuzzyDocument>("PUT", `/api/fuzzy/${encodeURIComponent(systemId)}`, document);
}

/** What-if: evaluate an (unsaved) rule base on one set of input values. */
export async function inferFuzzy(document: FuzzyDocument, inputs: Record<string, number>): Promise<FuzzyInference> {
  return sendJson<FuzzyInference>("POST", "/api/fuzzy/infer", { document, inputs });
}

/** Replay an (unsaved) rule base over a dataset: what it would have said. */
export async function replayFuzzy(
  datasetId: string,
  document: FuzzyDocument,
  options?: { startS?: number; endS?: number; maxPoints?: number },
): Promise<FuzzyReplay> {
  const body = { document, start_s: options?.startS, end_s: options?.endS, max_points: options?.maxPoints };
  return sendJson<FuzzyReplay>("POST", `/api/datasets/${encodeURIComponent(datasetId)}/fuzzy/replay`, body);
}

/** One structural difference between two rule bases (`POST /api/fuzzy/diff`): a code plus parameters. */
export interface FuzzyChange {
  code:
    | "variable_added"
    | "variable_removed"
    | "range_changed"
    | "term_added"
    | "term_removed"
    | "term_changed"
    | "rule_added"
    | "rule_removed"
    | "rule_changed";
  variable?: string;
  term?: string;
  rule?: string;
  /** Present on `range_changed` ([low, high]) and `term_changed` ({shape, params}). */
  old?: unknown;
  new?: unknown;
  /** Present on `rule_changed`: names among "if", "then", "operator", "weight", "enabled". */
  fields?: string[];
}

/** Version ids (UTC `YYYYMMDDTHHMMSSffffffZ`) of the saved snapshots of a rule base, newest first. */
export async function fetchFuzzyVersions(systemId: string): Promise<string[]> {
  return getJson<string[]>(`/api/fuzzy/${encodeURIComponent(systemId)}/versions`);
}

/** One saved snapshot of a rule base. */
export async function fetchFuzzyVersion(systemId: string, versionId: string): Promise<FuzzyDocument> {
  const base = `/api/fuzzy/${encodeURIComponent(systemId)}/versions/${encodeURIComponent(versionId)}`;
  return getJson<FuzzyDocument>(base);
}

/** What changed from `oldDocument` to `newDocument`. */
export async function diffFuzzy(oldDocument: FuzzyDocument, newDocument: FuzzyDocument): Promise<FuzzyChange[]> {
  return sendJson<FuzzyChange[]>("POST", "/api/fuzzy/diff", { old: oldDocument, new: newDocument });
}

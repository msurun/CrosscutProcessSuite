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
  /** Stable machine code of an input error (valve test routes), for the UI to translate. */
  readonly code: string | null;
  /** The request field the error is about, when the server names one. */
  readonly field: string | null;

  constructor(status: number, message: string, code: string | null = null, field: string | null = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.field = field;
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
/** "not_assessed": nothing fired, but some checks were withheld for missing loop data. */
export type LoopStatus = "ok" | "warning" | "problem" | "unused" | "not_assessed";

/** One finding as a stable code plus numeric parameters; the UI turns it into a sentence. */
export interface LoopFinding {
  code: string;
  params: Record<string, number>;
  /** Stretch of data behind the finding, [start_s, end_s] since the first sample; absent for whole-record findings. */
  window_s?: [number, number];
  /** "cause": the stretch produced the finding; "example": a representative stretch for a whole-record finding. */
  window_kind?: "cause" | "example";
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
  saturation_percent: number | null; // null: OUT range not configured
  harris_index: number | null;
  oscillation_period_s: number | null;
  stiction_verdict: string;
  /** "hagglund" (limits configured), "acf" (regularity only) or null when no cycle was found. */
  oscillation_method: "hagglund" | "acf" | null;
  /** Ranked stiction suspicion 0..1; null when the loop could not be ranked. */
  stiction_suspicion: number | null;
  /** "test_valve" or "not_ranked" (the backend may add codes; unknown ones are shown verbatim). */
  stiction_advice: string;
  valve_travel_per_h: number | null;
  valve_reversals_per_h: number | null;
  /** OUT step size relative to the loop's noise; large values mean a coarse output. */
  out_quantisation_ratio: number | null;
  valve_sizing_hint: string | null;
  /** Conclusions withheld for missing per-loop knowledge: saturation, valve_kpis, harris, oscillation_amplitude. */
  not_assessed: string[];
  /** Other loops cycling at about the same period (a hint of a shared disturbance). */
  same_period_as: string[];
  /** The one thing to do next, from the worklist rules. */
  next_action: NextAction;
  /** 1 = look at this loop first; unique per dataset. */
  priority_rank: number;
  sparkline: (number | null)[];
}

/** Worklist action codes the backend can return (see `loops/worklist.py`). */
export type NextActionCode =
  | "ask_why_manual"
  | "check_measurement"
  | "check_output_limit"
  | "valve_test"
  | "find_common_source"
  | "test_cycle_cause"
  | "check_output_resolution"
  | "bump_test_and_retune"
  | "review_valve_sizing"
  | "configure_knowledge"
  | "none";

/** One worklist action: a stable code plus parameters (percent, ratio, loops, missing, hint). */
export interface NextAction {
  code: NextActionCode;
  params: Record<string, number | string | readonly string[] | null>;
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
  /** PV standard deviation before a retune; with stdAfter it replaces the slider value. */
  stdBefore?: number;
  /** PV standard deviation after a retune; zero is allowed. */
  stdAfter?: number;
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
    /** "assumed" for a slider value, "retune_measured" when it comes from a before/after retune. */
    std_reduction_source: "assumed" | "retune_measured";
    std_before: number | null;
    std_after: number | null;
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
  if (inputs?.stdBefore !== undefined && inputs.stdBefore > 0) query.set("std_before", String(inputs.stdBefore));
  if (inputs?.stdAfter !== undefined && inputs.stdAfter >= 0) query.set("std_after", String(inputs.stdAfter));
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
    let code: string | null = null;
    let field: string | null = null;
    try {
      const detail = ((await response.json()) as { detail?: unknown }).detail;
      if (typeof detail === "string") message = detail;
      else if (typeof detail === "object" && detail !== null) {
        // Structured input error: {code, message, field}.
        const info = detail as { code?: unknown; message?: unknown; field?: unknown };
        if (typeof info.message === "string") message = info.message;
        if (typeof info.code === "string") code = info.code;
        if (typeof info.field === "string") field = info.field;
      }
    } catch {
      // keep the status text
    }
    throw new ApiError(response.status, message, code, field);
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

/** Per-loop knowledge kept in the dataset's project.json; null means "not given". */
export interface LoopKnowledgeValues {
  /** Process dead time in seconds (unlocks the Harris index). */
  delay_s: number | null;
  /** Period of the loop's natural oscillation in seconds (with the amplitude limit: oscillation amplitude). */
  ultimate_period_s: number | null;
  /** Acceptable oscillation amplitude in PV units. */
  amplitude_limit: number | null;
  process_kind: "self_regulating" | "integrating";
  /** Engineering range of the measurement, any sign; overrides the tag dictionary row. */
  pv_eng_min: number | null;
  pv_eng_max: number | null;
  /** Engineering range of the controller output; overrides the tag dictionary row. */
  out_eng_min: number | null;
  out_eng_max: number | null;
}

/** Range taken from the tag dictionary row; null where the row has no value. */
export interface RangeDefault {
  min: number | null;
  max: number | null;
}

/** Result of `GET/PUT /api/datasets/{id}/loops/{loop}/knowledge`. */
export interface LoopKnowledge {
  loop: string;
  knowledge: LoopKnowledgeValues;
  /** True once a project.json exists for the dataset. */
  saved: boolean;
  /** Engineering ranges the tags already give, [low, high] or null when not configured. */
  ranges: { pv: [number, number] | null; out: [number, number] | null };
  /** Tag-row ranges, shown as placeholders for the loop-level range fields. */
  pv_eng_default: RangeDefault;
  out_eng_default: RangeDefault;
}

/** The part of the knowledge the user changes; null clears a value. */
export type LoopKnowledgeUpdate = Partial<LoopKnowledgeValues>;

function knowledgeUrl(datasetId: string, loopName: string): string {
  return `${API_PREFIX}/datasets/${encodeURIComponent(datasetId)}/loops/${encodeURIComponent(loopName)}/knowledge`;
}

/** Read what is known about a loop (delay, ultimate period, amplitude limit, process kind). */
export async function fetchKnowledge(datasetId: string, loopName: string): Promise<LoopKnowledge> {
  return getJson<LoopKnowledge>(knowledgeUrl(datasetId, loopName));
}

/** Save loop knowledge to the dataset's project.json (local configuration; nothing goes to a plant). */
export async function saveKnowledge(
  datasetId: string,
  loopName: string,
  update: LoopKnowledgeUpdate,
): Promise<LoopKnowledge> {
  return sendJson<LoopKnowledge>("PUT", knowledgeUrl(datasetId, loopName), update);
}

/** Settings of a valve stroke test (all numbers; the server fills defaults for the optional ones). */
export interface ValvePlanRequest {
  op_start: number;
  dwell_s: number;
  op_low?: number;
  op_high?: number;
  /** Abort band in PV units: the operator stops when the PV leaves it. */
  pv_band?: number | null;
  step_sizes?: number[];
  steps_per_leg?: number[];
}

/** One operator instruction as a stable code plus parameters (the UI turns it into a sentence). */
export interface ValveProcedureStep {
  code: "manual" | "abort" | "set_start" | "step" | "return_auto";
  params: { op?: number; op_start?: number; dwell_s?: number; pv_band?: number | null };
}

/** A stroke test plan with its operator procedure (`POST /api/valve-test/plan`). */
export interface ValvePlan {
  op_start: number;
  dwell_s: number;
  op_low: number;
  op_high: number;
  pv_band: number | null;
  step_sizes: number[];
  steps_per_leg: number[];
  n_steps: number;
  total_s: number;
  steps: { index: number; op_target: number; direction: number; size: number; after_reversal: boolean }[];
  procedure: ValveProcedureStep[];
}

/** One detected OP step and the PV response to it. */
export interface ValveMove {
  start_index: number;
  op_change: number;
  pv_change: number | null;
  moved: boolean;
  size: number;
  after_reversal: boolean;
}

/** Result of analysing a recorded stroke test (deadband, resolution, gain, noise). */
export interface ValveResult {
  deadband: number | null;
  deadband_bracket: [number, number] | null;
  deadband_lower_bound: number | null;
  resolution_le: number | null;
  gain: number | null;
  sigma_pv: number | null;
  pv_left_band: boolean;
  /** "" when complete; "no_gain", "no_move_after_reversal" or "other" when incomplete. */
  reason_code: string;
  reason: string;
  moves: ValveMove[];
}

/** The analysis response: the result plus the analysed record (decimated) for plotting. */
export interface ValveAnalysis {
  result: ValveResult;
  record: {
    n_samples: number;
    start_s: number;
    end_s: number;
    series: { t_s: number[]; op: number[]; pv: number[] };
  };
}

/** Build a stroke test plan and the operator procedure. Nothing is written to the plant. */
export async function planValveTest(request: ValvePlanRequest): Promise<ValvePlan> {
  return sendJson<ValvePlan>("POST", `${API_PREFIX}/valve-test/plan`, request);
}

/** Analyse a stroke test recorded inside a window of the dataset (seconds since the first sample). */
export async function analyseValveWindow(
  datasetId: string,
  loopName: string,
  plan: ValvePlanRequest,
  window: { startS: number; endS: number } | null,
): Promise<ValveAnalysis> {
  const body = { plan, start_s: window?.startS ?? null, end_s: window?.endS ?? null };
  const base = `${API_PREFIX}/datasets/${encodeURIComponent(datasetId)}/loops/${encodeURIComponent(loopName)}`;
  return sendJson<ValveAnalysis>("POST", `${base}/valve-test/analyse`, body);
}

/** Analyse a stroke test from CSV text (columns t_s, OP, PV); parsed in memory by the server. */
export async function analyseValveCsv(
  plan: ValvePlanRequest,
  csvText: string,
  columns?: { t?: string; op?: string; pv?: string },
): Promise<ValveAnalysis> {
  return sendJson<ValveAnalysis>("POST", `${API_PREFIX}/valve-test/analyse-csv`, {
    plan,
    csv_text: csvText,
    columns: columns ?? null,
  });
}

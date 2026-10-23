// Typed client of the step analyzer endpoint (see docs/design/step-analyzer.md).
// One control loop per call: the server finds the steps, fits FOPDT/IPDT models with
// uncertainties and returns JSON rows the Steps view renders. This file also parses the
// logbook text the user types and formats parameter values for the table.
import type { StatusLevel } from "./components/StatusChip";

/** Prefix of every endpoint used here; the rest of the client uses the same `/api` root. */
const API_PREFIX = "/api";

/** Default decimals used when formatting a parameter value and its standard error. */
const DEFAULT_DIGITS = 2;

/** Minutes accepted around an event when matching logbook lines to a step. */

/** One fitted parameter: value and standard error, either may be unknown (null). */
export interface StepParam {
  value: number | null;
  se: number | null;
}

/** Fitted parameters of one step; only the ones the model defines are present. */
export interface StepParams {
  gain?: StepParam;
  tau_s?: StepParam;
  theta_s?: StepParam;
  slope?: StepParam;
}

/** One logbook line attached to a step, in UTC. */
export interface LogbookEntry {
  time_utc: string;
  text: string;
}

/** Samples of a step window, in seconds from the window start; `fit` may hold holes. */
export interface StepSample {
  t_s: number[];
  pv: number[];
  out: number[];
  fit: (number | null)[];
}

/** The other model fitted for this step (only present when `model` is "auto"). */
export interface AltModel {
  model: "fopdt" | "ipdt";
  bic: number;
}

/** One detected step with its fit, verdict and alignment. */
export interface StepRow {
  id: string;
  kind: "out_step" | "sp_step";
  mode: "manual" | "auto";
  closed_loop: boolean;
  start_utc: string;
  event_utc: string;
  end_utc: string;
  size: number;
  snr: number | null;
  model: "fopdt" | "ipdt" | null;
  params: StepParams;
  r2: number | null;
  rmse: number | null;
  n: number;
  verdict: "ok" | "weak" | "unusable";
  reasons: string[];
  alt_model: AltModel | null;
  test_label: string | null;
  logbook: LogbookEntry[];
  sample: StepSample;
  /** Optional extra server text (not in the base payload; shown when present). */
  detail?: string;
}

/** Robust summary of the consistent rows of one model. */
export interface StepSummary {
  model: "fopdt" | "ipdt";
  n_rows: number;
  n_consistent: number;
  median_gain: number | null;
  mad_gain: number | null;
  median_slope: number | null;
  mad_slope: number | null;
  median_tau_s: number | null;
  median_theta_s: number | null;
}

/** One event that was dropped before fitting, with the reason code. */
export interface SkippedStep {
  event_utc: string;
  reason: string;
}

/** Reply of `POST /api/datasets/{id}/steps`: every step of one loop plus summaries. */
export interface StepsPayload {
  loop: string;
  process_kind: string;
  unit: string;
  dt_s: number;
  noise_sd: number | null;
  n_events: number;
  rows: StepRow[];
  skipped: SkippedStep[];
  summary?: StepSummary[];
}

/** Body of the analyze request; `model` defaults to "auto" on the server. */
export interface StepsRequest {
  loop: string;
  model?: "auto" | "fopdt" | "ipdt";
  logbook?: LogbookEntry[];
}

/**
 * Analyze the steps of one loop of a dataset.
 * @throws {Error} With the server message on a non-2xx status (404 unknown loop, 422 bad body).
 */
export async function analyzeSteps(
  datasetId: string,
  body: StepsRequest,
): Promise<StepsPayload> {
  const url = `${API_PREFIX}/datasets/${encodeURIComponent(datasetId)}/steps`;
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model: "auto", logbook: [], ...body }),
  });
  return readJson<StepsPayload>(response);
}

/** Matches `YYYY-MM-DD HH:MM[:SS] text` or `YYYY-MM-DDTHH:MM[:SS] text`. */
const LOGBOOK_LINE_PATTERN =
  /^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)\s+(.*\S)\s*$/;

/** Hours in one day, used to turn a day offset into milliseconds. */
const MS_PER_HOUR_S = 3_600_000;

/**
 * Parse logbook text typed as local time at `offsetHours` east of UTC.
 * Accepts lines `YYYY-MM-DD HH:MM[:SS] description` or `YYYY-MM-DDTHH:MM... description`;
 * unreadable lines are skipped.
 * @returns Entries with `time_utc` as ISO text with a `Z` suffix, in input order.
 */
export function parseLogbook(
  text: string,
  offsetHours: number,
): LogbookEntry[] {
  const entries: LogbookEntry[] = [];
  for (const line of text.split(/\r?\n/)) {
    const entry = parseLogbookLine(line.trim(), offsetHours);
    if (entry !== null) entries.push(entry);
  }
  return entries;
}

/** Parse one trimmed logbook line, or return null when it cannot be read. */
function parseLogbookLine(line: string, offsetHours: number): LogbookEntry | null {
  const match = LOGBOOK_LINE_PATTERN.exec(line);
  if (match === null) return null;
  const [, date, time, description] = match;
  const withSeconds = time.length === 5 ? `${time}:00` : time;
  const local = new Date(`${date}T${withSeconds}Z`);
  if (Number.isNaN(local.getTime())) return null;
  const utc = new Date(local.getTime() - offsetHours * MS_PER_HOUR_S);
  return { time_utc: utc.toISOString(), text: description };
}

/**
 * Format a parameter as "value ± se" with `digits` decimals.
 * @returns "–" (en dash) when the parameter or its value is missing.
 */
export function paramText(
  param: StepParam | undefined,
  digits: number = DEFAULT_DIGITS,
): string {
  if (param === undefined || param.value === null) return "\u2013";
  if (param.se === null) return param.value.toFixed(digits);
  return `${param.value.toFixed(digits)} \u00B1 ${param.se.toFixed(digits)}`;
}

/** Map a step verdict to the chip level used by {@link StatusChip}. */
export function verdictClass(verdict: StepRow["verdict"]): StatusLevel {
  if (verdict === "ok") return "ok";
  if (verdict === "weak") return "warning";
  return "problem";
}

/** Read the error message out of a failed response. */
async function readErrorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    const detail = (body as Record<string, unknown> | null)?.["detail"];
    if (typeof detail === "string") return detail;
  } catch {
    // Body was empty or not JSON: fall through to the status text.
  }
  return response.statusText;
}

/** Parse the JSON body of `response`. @throws {Error} With the server message on failure. */
async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
  return (await response.json()) as T;
}

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

/**
 * Body of the analyze request: either a `loop`, or a `driver` tag (stepped) and an `output`
 * tag (response). `model` defaults to "auto" on the server.
 */
export interface StepsRequest {
  loop?: string;
  driver?: string;
  output?: string;
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

/** Roles of the logbook CSV columns; each role accepts its Spanish and English header names. */
type CsvRole = "day" | "time" | "change" | "unit" | "cells" | "notes";

const CSV_HEADERS: Record<CsvRole, readonly string[]> = {
  day: ["dia", "day"],
  time: ["hora", "log_time"],
  change: ["zmiana", "change"],
  unit: ["jednostka", "unit"],
  cells: ["cele", "cells_logbook"],
  notes: ["uwagi", "notes", "text"],
};

/** Column position of each role in the CSV header; missing roles are absent. */
type ColumnIndex = Partial<Record<CsvRole, number>>;

/**
 * Convert a logbook CSV (`dia,hora,zmiana,jednostka,cele,uwagi` or the English header)
 * into textarea lines `YYYY-MM-DD HH:MM description`, one per readable data row.
 * Rows without a valid date and time are skipped.
 */
export function logbookFromCsv(csv: string): string {
  const [header = [], ...dataRows] = splitCsv(csv.replace(/^﻿/, ""));
  const index = columnIndex(header.map((name) => name.trim().toLowerCase()));
  const lines = dataRows.map((cells) => logbookLineFromCells(cells, index));
  return lines.filter((line): line is string => line !== null).join("\n");
}

/** Map each role to the position of its header name, using the first matching column. */
function columnIndex(names: string[]): ColumnIndex {
  const index: ColumnIndex = {};
  for (const role of Object.keys(CSV_HEADERS) as CsvRole[]) {
    const position = names.findIndex((name) => CSV_HEADERS[role].includes(name));
    if (position >= 0) index[role] = position;
  }
  return index;
}

/** Build one textarea line from a data row, or return null when its date or time is unreadable. */
function logbookLineFromCells(cells: string[], index: ColumnIndex): string | null {
  const field = (role: CsvRole) => (index[role] === undefined ? "" : (cells[index[role]] ?? "").trim());
  const notes = field("notes");
  const description = `${field("change")} ${field("unit")}, cells ${field("cells")}${notes === "" ? "" : ` - ${notes}`}`;
  const line = `${field("day")} ${field("time")} ${description}`.replace(/[\r\n]+/g, " ");
  return parseLogbookLine(line, 0) === null ? null : line;
}

/**
 * Split CSV text into rows of cells (RFC 4180: quoted cells may hold commas, newlines and
 * doubled quotes; rows end at CRLF or LF).
 */
function splitCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let pos = 0;
  while (pos < text.length) {
    CSV_CELL.lastIndex = pos;
    const match = CSV_CELL.exec(text);
    if (match === null) break;
    row.push(unquoteCell(match[1]));
    pos = CSV_CELL.lastIndex;
    if (match[2] !== undefined && match[2] !== ",") {
      rows.push(row);
      row = [];
    }
  }
  if (row.length > 0) rows.push(row);
  return rows;
}

/** One CSV cell (quoted or bare) and the delimiter after it; sticky so cells are read in order. */
const CSV_CELL = /("(?:[^"]|"")*"|[^,\r\n]*)(,|\r\n|\r|\n)?/y;

/** Strip the enclosing quotes of a quoted cell and un-double its inner quotes. */
function unquoteCell(raw: string): string {
  const quoted = raw.length >= 2 && raw.startsWith('"') && raw.endsWith('"');
  return quoted ? raw.slice(1, -1).replace(/""/g, '"') : raw;
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

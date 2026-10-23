// Typed client of the plant CSV import endpoints (see docs/design/plant-import-gui.md).
// Uploads a data file and an optional tag dictionary, then previews or imports a whole plant
// (several loops at once). Parsing and time-zone handling live on the server; this file only
// moves bytes, shapes request bodies and turns server note codes into sentences.
import type { Translate } from "./findings";

/** How the server should read the timestamps of the data file. */
export type TimeZoneBody = { kind: "utc" | "iana" | "offset"; value: string | number | null };

/** One control loop the preview found in the data file. */
export interface PlantLoop {
  id: string;
  name: string;
  process_kind: "integrating" | "self_regulating";
  pv: string | null;
  sp: string | null;
  out: string | null;
  mode: string | null;
  feedback: string | null;
  valves: string[];
  unit: string;
  cell: string;
  complete: boolean;
  missing: string[];
}

/** A stretch without samples, as UTC timestamps plus its length in seconds. */
export interface PlantGap {
  start_utc: string;
  end_utc: string;
  seconds: number;
}

/** A stretch of the data file the backend would use as a step-test window. */
export interface PlantWindow {
  label: string;
  start_utc: string;
  end_utc: string;
  rows: number;
}

/** One server note: a stable code, its English text and the figures behind it. */
export interface PlantNote {
  code: string;
  text: string;
  params: Record<string, unknown>;
}

/** Reply of `POST /intake/plant/preview`: what the server read, without writing anything. */
export interface PlantPreview {
  n_rows: number;
  n_columns: number;
  start_local: string;
  end_local: string;
  start_utc: string;
  end_utc: string;
  period_s: number;
  n_gaps: number;
  gaps: PlantGap[];
  loops: PlantLoop[];
  skipped: { count: number; reason: string };
  test_windows: PlantWindow[];
  notes: PlantNote[];
}

/** Reply of `POST /intake/plant/import`: the created dataset and what was written. */
export interface PlantImportResult {
  dataset_id: string;
  loops: PlantLoop[];
  notes: PlantNote[];
  tags_written: number;
  tags_skipped: number;
  test_windows: PlantWindow[];
}

/** The time-zone choices offered by the form. */
export type TzPreset = "utc" | "santiago" | "offset";

/** The largest offset accepted from the form, in hours (RFC 3339 allows -14..+14). */
const MAX_OFFSET_HOURS = 14;
/** Time zone of the plant site the presets were written for. */
const SANTIAGO_ZONE = "America/Santiago";
/** Dataset ids may be used as folder names, so only these characters are allowed. */
const DATASET_ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;
/** Prefix of every endpoint used here; the rest of the client uses the same `/api` root. */
const API_PREFIX = "/api";
/** Binary uploads are sent as a raw body, not as multipart form data. */
const OCTET_STREAM = "application/octet-stream";

/**
 * Build the time-zone body from the form choice.
 * The offset is read from text and accepts a dot or a comma as the decimal separator (some locales
 * show "‑3,5"), because site engineers type both.
 * @returns The body, or null when the preset is "offset" and the text is not a number in -14..14.
 */
export function timezoneBody(preset: TzPreset, offsetHours: string): TimeZoneBody | null {
  if (preset === "utc") return { kind: "utc", value: null };
  if (preset === "santiago") return { kind: "iana", value: SANTIAGO_ZONE };
  const hours = Number(offsetHours.replace(",", ".").trim());
  if (offsetHours.trim() === "" || !Number.isFinite(hours) || Math.abs(hours) > MAX_OFFSET_HOURS) {
    return null;
  }
  return { kind: "offset", value: hours };
}

/** True when `id` can be used as a dataset id (letters, digits, `_`, `-`, 1 to 64 characters). */
export function validDatasetId(id: string): boolean {
  return DATASET_ID_PATTERN.test(id);
}

/** Server parameter names to use for each placeholder of a `plant.note.<code>` message. */
const NOTE_PLACEHOLDERS: Record<string, Record<string, string>> = {
  tz_iana: { zone: "zone", first: "offset_first_hours", last: "offset_last_hours" },
  tz_utc: {},
  out_range_assumed: { loops: "loops" },
  mode_leading_gap: {},
  tz_offset: { hours: "hours" },
  gaps: { count: "count", period: "median_period_s" },
  read_plant: { rows: "rows", columns: "columns" },
  import_scope: { scope: "scope", written: "written", skipped: "skipped" },
  tz_ambiguous: { rows: "rows" },
  tz_nonexistent: { rows: "rows" },
};

/**
 * Translate one server note: the key `plant.note.<code>` with the note's figures as text.
 * Falls back to the server's English text when the code is unknown (the translator then returns
 * the key itself) or a figure is missing.
 */
export function noteText(note: PlantNote, t: Translate): string {
  return translateNote(note, t) ?? note.text;
}

/** The translated note, or null when the message cannot be filled in (see {@link noteText}). */
function translateNote(note: PlantNote, t: Translate): string | null {
  const values = noteValues(note);
  if (values === null) return null;
  const key = `plant.note.${note.code}`;
  const message = t(key, values);
  return message === key ? null : message;
}

/** Figure values of a note, or null when a placeholder has no matching parameter. */
function noteValues(note: PlantNote): Record<string, string> | null {
  const placeholders = NOTE_PLACEHOLDERS[note.code];
  if (placeholders === undefined) return null;
  const values: Record<string, string> = {};
  for (const [placeholder, param] of Object.entries(placeholders)) {
    const raw = note.params[param];
    if (raw === undefined || raw === null) return null;
    values[placeholder] = String(raw);
  }
  return values;
}

/**
 * Upload one CSV file and keep it on the server for the next preview or import.
 * The raw file bytes are the request body; the server answers with an id and the byte count.
 * @throws {ApiError} On a non-2xx response (for example 413 when the file is too large).
 */
export async function uploadPlantFile(
  role: "data" | "dictionary",
  file: File,
): Promise<{ upload_id: string; bytes: number }> {
  const url = `${API_PREFIX}/intake/plant/upload?role=${role}`;
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": OCTET_STREAM },
    body: file,
  });
  return readJson<{ upload_id: string; bytes: number }>(response);
}

/** Describe what the two uploaded files contain: rows, range, loops, gaps and test windows. */
export async function previewPlant(body: {
  data_upload: string;
  dictionary_upload: string | null;
  timezone: TimeZoneBody;
}): Promise<PlantPreview> {
  return sendJson<PlantPreview>("POST", `${API_PREFIX}/intake/plant/preview`, body);
}

/** Create the dataset from the uploaded files. Nothing is written to a plant. */
export async function importPlant(body: {
  data_upload: string;
  dictionary_upload: string | null;
  timezone: TimeZoneBody;
  scope: "loops" | "process";
  dataset_id: string;
}): Promise<PlantImportResult> {
  return sendJson<PlantImportResult>("POST", `${API_PREFIX}/intake/plant/import`, body);
}

/** Delete an upload the user no longer needs (also when the page starts over). */
export async function deletePlantUpload(uploadId: string): Promise<void> {
  const response = await fetch(`${API_PREFIX}/intake/plant/upload/${encodeURIComponent(uploadId)}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
}

/**
 * Read the error message out of a failed response.
 * Returns the `detail` field when the body is JSON with a string detail, the status text otherwise.
 */
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

/** Parse the JSON body of `response`. @throws {Error} With the server message on a non-2xx status. */
async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
  return (await response.json()) as T;
}

/** POST `body` as JSON and parse the reply. @throws {Error} With the server message on a non-2xx status. */
async function sendJson<T>(method: string, url: string, body: unknown): Promise<T> {
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readJson<T>(response);
}

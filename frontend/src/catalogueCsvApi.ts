// Typed client for the catalogue tag CSV round trip (issue #144): download the site tags as CSV
// and read a CSV back in, as a dry run or a real import.
// Reuses apiFetch from http.ts and API_PREFIX/ApiError from api.ts; a refused import (422)
// resolves with its row errors instead of throwing.
import { API_PREFIX, ApiError } from "./api";
import { apiFetch } from "./http";

/** The site tag CSV route: GET downloads it, POST imports it back. */
const TAGS_CSV_PATH = `${API_PREFIX}/site/tags.csv`;
/** The media type the CSV body travels as in the POST request. */
const CSV_MEDIA_TYPE = "text/csv";
/** The status a refused real import answers with; dry runs always answer 200. */
const IMPORT_REFUSED_STATUS = 422;

/** One problem found in a tag CSV (row 0 names the header line or the whole file). */
export type CsvRowError = {
  row: number;
  column: string;
  message: string;
};

/** The JSON answer of an import attempt: the problems, the tag count, whether it saved. */
export type CsvImportResult = {
  errors: CsvRowError[];
  tags: number;
  applied: boolean;
};

/**
 * Download the site's tags as CSV text.
 * @throws {ApiError} On a non-2xx response, for example 404 when the project has no site yet.
 */
export async function downloadTagsCsv(): Promise<string> {
  const response = await apiFetch(TAGS_CSV_PATH);
  if (!response.ok) throw new ApiError(response.status, response.statusText);
  return response.text();
}

/**
 * Read a tag CSV back in; with `dryRun` the server only checks it and never saves.
 * A refused import answers 422 and still resolves, with its row errors in the result.
 * @throws {ApiError} On any other non-2xx response, for example 404 when the site is missing.
 */
export async function importTagsCsv(csv: string, dryRun: boolean): Promise<CsvImportResult> {
  const response = await apiFetch(`${TAGS_CSV_PATH}?dry_run=${dryRun}`, {
    method: "POST",
    headers: { "Content-Type": CSV_MEDIA_TYPE },
    body: csv,
  });
  if (!response.ok && response.status !== IMPORT_REFUSED_STATUS) {
    throw new ApiError(response.status, response.statusText);
  }
  return (await response.json()) as CsvImportResult;
}

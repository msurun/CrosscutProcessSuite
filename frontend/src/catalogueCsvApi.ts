// Typed client for the catalogue tag CSV round trip (issue #144): the site's
// tags go out as a CSV for spreadsheet editing and come back through the same
// route. Reuses apiFetch from http.ts and ApiError/API_PREFIX from api.ts.
// A 422 answer is the server's normal "here are the problems" reply, so
// importTagsCsv resolves it instead of throwing.
import { API_PREFIX, ApiError } from "./api";
import { apiFetch } from "./http";

/** HTTP status of an import the server refused with row problems (a normal answer, not a failure). */
const IMPORT_REFUSED_STATUS = 422;

/** The route that hands out the site's tags and reads the edited file back. */
const TAGS_CSV_PATH = `${API_PREFIX}/site/tags.csv`;

/** Media type the tag CSV travels as; same value as the server's CSV_MEDIA_TYPE. */
const CSV_MEDIA_TYPE = "text/csv";

/** One problem the server found in the CSV it read back. */
export type CsvRowError = {
  /** 0-based CSV line the problem is on; 0 is the header or a problem of the whole file. */
  row: number;
  /** Column the problem is in; empty when the problem is about the whole row. */
  column: string;
  /** What is wrong, in words for the person fixing the file. */
  message: string;
};

/** The server's answer to a CSV import attempt. */
export type CsvImportResult = {
  /** Problems found in the file; empty when the file was clean. */
  errors: CsvRowError[];
  /** How many tags the file carries, problems or not. */
  tags: number;
  /** True only when the import was saved into the site file. */
  applied: boolean;
};

/**
 * Download the site's tags as CSV text, ready for editing in a spreadsheet.
 * @throws {ApiError} On a non-2xx response, for example 404 when the project has no site file yet.
 */
export async function downloadTagsCsv(): Promise<string> {
  const response = await apiFetch(TAGS_CSV_PATH);
  if (!response.ok) throw new ApiError(response.status, response.statusText);
  return response.text();
}

/**
 * Send an edited tag CSV back to the server.
 * @param csv CSV text exactly as downloaded (the header row is part of the format).
 * @param dryRun True to only check the file; false to save it into the site file when clean.
 * @returns The server's answer: row problems, tag count and whether the import was saved.
 *   A 422 refused import resolves like a 200; its body is the result.
 * @throws {ApiError} On any other non-2xx response, for example 404 when the site file is gone.
 */
export async function importTagsCsv(csv: string, dryRun: boolean): Promise<CsvImportResult> {
  const url = `${TAGS_CSV_PATH}?dry_run=${dryRun}`;
  const response = await apiFetch(url, {
    method: "POST",
    headers: { "Content-Type": CSV_MEDIA_TYPE },
    body: csv,
  });
  if (!response.ok && response.status !== IMPORT_REFUSED_STATUS) {
    throw new ApiError(response.status, response.statusText);
  }
  return (await response.json()) as CsvImportResult;
}

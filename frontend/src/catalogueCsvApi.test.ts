// Tests for the catalogue tag CSV client: the download text, the POST request shape with the dry
// run flag, the refused import (422 resolves), and a server failure (ApiError). fetch is stubbed.
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./api";
import {
  CsvImportResult,
  CsvRowError,
  downloadTagsCsv,
  importTagsCsv,
} from "./catalogueCsvApi";

const CSV_SAMPLE = "tag,unit\nT1,bar\n";

function stub(status: number, body: unknown) {
  const text = typeof body === "string" ? body : JSON.stringify(body);
  const fn = vi.fn().mockResolvedValue(new Response(text, { status }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("catalogueCsvApi", () => {
  it("downloads the tags CSV text from the site route", async () => {
    const fn = stub(200, CSV_SAMPLE);
    expect(await downloadTagsCsv()).toBe(CSV_SAMPLE);
    expect(fn.mock.calls[0][0]).toBe("/api/site/tags.csv");
  });

  it("posts the CSV as text/csv with dry_run=true", async () => {
    const fn = stub(200, { errors: [], tags: 1, applied: false });
    await importTagsCsv(CSV_SAMPLE, true);
    const [url, init] = fn.mock.calls[0];
    expect(url).toBe("/api/site/tags.csv?dry_run=true");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(CSV_SAMPLE);
    expect(init.headers["Content-Type"]).toBe("text/csv");
  });

  it("sends dry_run=false and returns the applied result for a real import", async () => {
    const fn = stub(200, { errors: [], tags: 1, applied: true });
    const result: CsvImportResult = await importTagsCsv(CSV_SAMPLE, false);
    expect(fn.mock.calls[0][0]).toBe("/api/site/tags.csv?dry_run=false");
    expect(result.applied).toBe(true);
    expect(result.tags).toBe(1);
  });

  it("resolves a refused import (422) with its row errors", async () => {
    const rowError: CsvRowError = { row: 2, column: "unit", message: "unknown unit" };
    stub(422, { errors: [rowError], tags: 0, applied: false });
    const result: CsvImportResult = await importTagsCsv(CSV_SAMPLE, false);
    expect(result.applied).toBe(false);
    expect(result.errors).toEqual([rowError]);
  });

  it("rejects a server failure (500) as an ApiError carrying the status", async () => {
    stub(500, "boom");
    let error: unknown;
    try {
      await importTagsCsv(CSV_SAMPLE, false);
    } catch (e) {
      error = e;
    }
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(500);
  });
});

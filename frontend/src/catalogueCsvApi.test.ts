// Tests for the catalogue tag CSV client: request shapes and the 422-resolves semantics.
// fetch is stubbed; no network.
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./api";
import { downloadTagsCsv, importTagsCsv } from "./catalogueCsvApi";

function stub(status: number, body: unknown) {
  const text = typeof body === "string" ? body : JSON.stringify(body);
  const fn = vi.fn().mockResolvedValue(new Response(text, { status }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

const SAMPLE_CSV = "tag,unit,description\nP1,degC,Reactor temperature\n";

describe("catalogueCsvApi", () => {
  it("downloads the tags CSV as text", async () => {
    const fn = stub(200, SAMPLE_CSV);
    expect(await downloadTagsCsv()).toBe(SAMPLE_CSV);
    expect(fn.mock.calls[0][0]).toBe("/api/site/tags.csv");
  });

  it("posts the CSV as text/csv with dry_run=true on a dry run", async () => {
    const fn = stub(200, { errors: [], tags: 1, applied: false });
    await importTagsCsv(SAMPLE_CSV, true);
    const [url, init] = fn.mock.calls[0];
    expect(url).toBe("/api/site/tags.csv?dry_run=true");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(SAMPLE_CSV);
    expect(init.headers["Content-Type"]).toBe("text/csv");
  });

  it("posts with dry_run=false for a real import", async () => {
    const fn = stub(200, { errors: [], tags: 1, applied: true });
    const result = await importTagsCsv(SAMPLE_CSV, false);
    expect(fn.mock.calls[0][0]).toBe("/api/site/tags.csv?dry_run=false");
    expect(result.applied).toBe(true);
  });

  it("resolves a 422 refused import with its row problems", async () => {
    const errors = [{ row: 2, column: "unit", message: "unknown unit" }];
    stub(422, { errors, tags: 0, applied: false });
    const result = await importTagsCsv(SAMPLE_CSV, false);
    expect(result.errors).toEqual(errors);
    expect(result.tags).toBe(0);
    expect(result.applied).toBe(false);
  });

  it("rejects a 500 with an ApiError carrying the status", async () => {
    stub(500, "boom");
    await expect(importTagsCsv(SAMPLE_CSV, false)).rejects.toBeInstanceOf(ApiError);
    stub(500, "boom");
    await expect(importTagsCsv(SAMPLE_CSV, false)).rejects.toMatchObject({ status: 500 });
  });
});

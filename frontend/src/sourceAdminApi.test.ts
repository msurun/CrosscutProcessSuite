// Tests for the source management client: request shapes and the 409 in-use error.
// fetch is stubbed; no network.
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  SourceInUseError,
  deleteSource,
  fetchSecretStored,
  putSecret,
  saveSource,
  testDraft,
} from "./sourceAdminApi";

function stub(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("sourceAdminApi", () => {
  it("saves with PUT and a body without the id", async () => {
    const fn = stub(200, { id: "pi", driver: "csv", secret_stored: false });
    await saveSource({ id: "pi", driver: "csv", endpoint: "/data" });
    const [url, init] = fn.mock.calls[0];
    expect(url).toBe("/api/sources/pi");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual({ driver: "csv", endpoint: "/data" });
  });

  it("turns a 409 source_in_use into SourceInUseError with the tags", async () => {
    stub(409, { detail: { code: "source_in_use", tags: ["T1", "T2"] } });
    await expect(deleteSource("pi")).rejects.toMatchObject({ tags: ["T1", "T2"] });
    stub(409, { detail: { code: "source_in_use", tags: [] } });
    await expect(deleteSource("pi")).rejects.toBeInstanceOf(SourceInUseError);
  });

  it("reads the secret status and sends the secret only to the secret route", async () => {
    stub(200, { stored: true });
    expect(await fetchSecretStored("pi")).toBe(true);
    const fn = stub(200, { stored: true });
    await putSecret("pi", "s3cret");
    expect(fn.mock.calls[0][0]).toBe("/api/sources/pi/secret");
    expect(JSON.parse(fn.mock.calls[0][1].body)).toEqual({ value: "s3cret" });
  });

  it("posts the draft including its id", async () => {
    const fn = stub(200, { status: "ok", capabilities: ["history"] });
    const report = await testDraft({ id: "d", driver: "csv" });
    expect(report.capabilities).toEqual(["history"]);
    expect(fn.mock.calls[0][0]).toBe("/api/sources/test-draft");
  });
});

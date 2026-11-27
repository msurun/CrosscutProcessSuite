// Tests for the backup client: URL, method and body per call, file name parsing, error mapping.
import { afterEach, describe, expect, it, vi } from "vitest";
import { API_PREFIX, ApiError } from "./api";
import { downloadBackup, inspectBackup, restoreBackup, type BackupReport } from "./backupApi";

const REPORT: BackupReport = {
  ok: true, archive_sha256: "abc", problems: [], created_utc: "2026-11-26T10:00:00Z",
  format_version: 1, changes: [], must_reenter: [],
};

function stubFetch(status: number, body: unknown, headers: Record<string, string> = {}) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: status < 400,
    status,
    statusText: "Error",
    headers: new Headers(headers),
    json: () => Promise.resolve(body),
    blob: () => Promise.resolve(new Blob(["zip"])),
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("backup client", () => {
  it("downloads the zip and reads the file name from the header", async () => {
    const fetchMock = stubFetch(200, null, { "Content-Disposition": 'attachment; filename="crosscut-backup-1.zip"' });
    const result = await downloadBackup();
    expect(fetchMock.mock.calls[0][0]).toBe(`${API_PREFIX}/admin/backup`);
    expect(result.filename).toBe("crosscut-backup-1.zip");
  });

  it("posts the file as the raw body for the dry run", async () => {
    const fetchMock = stubFetch(200, REPORT);
    const file = new Blob(["zip"]);
    expect(await inspectBackup(file)).toEqual(REPORT);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${API_PREFIX}/admin/backup/inspect`);
    expect(init.method).toBe("POST");
    expect(init.body).toBe(file);
  });

  it("sends the confirmation hash on restore", async () => {
    const fetchMock = stubFetch(200, REPORT);
    await restoreBackup(new Blob(["zip"]), "a b");
    expect(fetchMock.mock.calls[0][0]).toBe(`${API_PREFIX}/admin/backup/restore?confirm=a%20b`);
  });

  it("joins a list of problems into the error message", async () => {
    stubFetch(422, { detail: ["first", "second"] });
    await expect(restoreBackup(new Blob(["zip"]), "x")).rejects.toMatchObject({
      status: 422,
      message: "first\nsecond",
    });
  });

  it("maps a string detail to an ApiError", async () => {
    stubFetch(409, { detail: "confirm_mismatch" });
    const error = await inspectBackup(new Blob(["zip"])).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toBe("confirm_mismatch");
  });
});

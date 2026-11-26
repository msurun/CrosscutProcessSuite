// frontend/src/components/BackupPage.test.tsx
/** Tests for the Backup page: denied notice, download, dry run report, and the confirmed restore. */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useCan } from "../AuthContext";
import { BackupPage } from "../BackupPage";
import { downloadBackup, inspectBackup, restoreBackup, type BackupReport } from "../backupApi";

vi.mock("../backupApi", () => ({ downloadBackup: vi.fn(), inspectBackup: vi.fn(), restoreBackup: vi.fn() }));
vi.mock("../AuthContext", () => ({ useCan: vi.fn() }));

const t = (key: string, params?: Record<string, string | number>) =>
  params ? `${key} ${JSON.stringify(params)}` : key;

const GOOD: BackupReport = {
  ok: true, archive_sha256: "sha1", problems: [], created_utc: "2026-11-26T10:00:00Z", format_version: 1,
  changes: [{ path: "_fuzzy/f1.json", action: "replace" }],
  must_reenter: [{ kind: "source_secret", source: "pi1", ref: "source.pi1" }, { kind: "gateway_key" }],
};
const BAD: BackupReport = { ...GOOD, ok: false, problems: ["_fuzzy/f1.json: content does not match"], changes: [] };

function chooseFile(): File {
  const file = new File(["zip"], "backup.zip", { type: "application/zip" });
  fireEvent.change(screen.getByLabelText("backup.restore.file"), { target: { files: [file] } });
  return file;
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(useCan).mockReturnValue({ allowed: true, reason: "" });
  URL.createObjectURL = vi.fn(() => "blob:x");
  URL.revokeObjectURL = vi.fn();
});

describe("BackupPage", () => {
  it("shows the denied notice without users.manage", () => {
    vi.mocked(useCan).mockReturnValue({ allowed: false, reason: "no" });
    render(<BackupPage t={t} />);
    expect(screen.getByText("backup.denied")).toBeInTheDocument();
  });

  it("lists what is excluded from the backup", () => {
    render(<BackupPage t={t} />);
    expect(screen.getByText("backup.excluded.datasets")).toBeInTheDocument();
    expect(screen.getByText("backup.excluded.secrets")).toBeInTheDocument();
  });

  it("downloads a backup and reports its name", async () => {
    vi.mocked(downloadBackup).mockResolvedValue({ blob: new Blob(["z"]), filename: "b.zip" });
    render(<BackupPage t={t} />);
    fireEvent.click(screen.getByText("backup.download.button"));
    expect(await screen.findByText('backup.downloaded {"name":"b.zip"}')).toBeInTheDocument();
  });

  it("keeps the check button disabled until a file is chosen", () => {
    render(<BackupPage t={t} />);
    expect(screen.getByText("backup.restore.check")).toBeDisabled();
  });

  it("shows the dry run, needs the confirmation, then restores the inspected archive", async () => {
    vi.mocked(inspectBackup).mockResolvedValue(GOOD);
    vi.mocked(restoreBackup).mockResolvedValue(GOOD);
    render(<BackupPage t={t} />);
    const file = chooseFile();
    fireEvent.click(screen.getByText("backup.restore.check"));
    expect(await screen.findByText("_fuzzy/f1.json")).toBeInTheDocument();
    expect(screen.getByText("backup.reenter.gatewayKey")).toBeInTheDocument();
    const restore = screen.getByText("backup.restore.button");
    expect(restore).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/backup\.restore\.confirm/));
    fireEvent.click(restore);
    await waitFor(() => expect(restoreBackup).toHaveBeenCalledWith(file, "sha1"));
    expect(await screen.findByText("backup.restored")).toBeInTheDocument();
  });

  it("offers no restore for a refused archive and lists the problems", async () => {
    vi.mocked(inspectBackup).mockResolvedValue(BAD);
    render(<BackupPage t={t} />);
    chooseFile();
    fireEvent.click(screen.getByText("backup.restore.check"));
    expect(await screen.findByText("_fuzzy/f1.json: content does not match")).toBeInTheDocument();
    expect(screen.queryByText("backup.restore.button")).not.toBeInTheDocument();
  });

  it("shows a server error", async () => {
    vi.mocked(inspectBackup).mockRejectedValue(new Error("boom"));
    render(<BackupPage t={t} />);
    chooseFile();
    fireEvent.click(screen.getByText("backup.restore.check"));
    expect(await screen.findByText("boom")).toBeInTheDocument();
  });
});

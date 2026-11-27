// frontend/src/components/CatalogueCsvPanel.test.tsx
/**
 * Tests for the catalogue CSV panel (issue #144): the download, a refused dry run, a clean
 * dry run, the apply step, and a server failure. The api module is mocked, as in BackupPage.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { downloadTagsCsv, importTagsCsv, type CsvImportResult } from "../catalogueCsvApi";
import { CatalogueCsvPanel } from "./CatalogueCsvPanel";

vi.mock("../catalogueCsvApi", () => ({ downloadTagsCsv: vi.fn(), importTagsCsv: vi.fn() }));

const t = (key: string, params?: Record<string, string | number>) =>
  params ? `${key} ${JSON.stringify(params)}` : key;

const CSV_TEXT = "id\nx1\n";
const REFUSED: CsvImportResult = {
  errors: [{ row: 2, column: "foo", message: "column is not a tag field of the schema" }],
  tags: 0,
  applied: false,
};
const CLEAN: CsvImportResult = { errors: [], tags: 2, applied: false };
const SAVED: CsvImportResult = { errors: [], tags: 2, applied: true };

function chooseFile(): void {
  // jsdom's File has no .text(), so give it the one the panel reads the CSV with.
  const file = new File([CSV_TEXT], "site-tags.csv", { type: "text/csv" });
  Object.assign(file, { text: () => Promise.resolve(CSV_TEXT) });
  fireEvent.change(screen.getByLabelText("catalogueCsv.file"), { target: { files: [file] } });
}

beforeEach(() => {
  vi.resetAllMocks();
  URL.createObjectURL = vi.fn(() => "blob:x");
  URL.revokeObjectURL = vi.fn();
});

describe("CatalogueCsvPanel", () => {
  it("downloads the site tags through the api and saves them as site-tags.csv", async () => {
    vi.mocked(downloadTagsCsv).mockResolvedValue(CSV_TEXT);
    render(<CatalogueCsvPanel t={t} />);
    fireEvent.click(screen.getByText("catalogueCsv.download"));
    await waitFor(() => expect(downloadTagsCsv).toHaveBeenCalledTimes(1));
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
  });

  it("lists the row errors of a refused dry run and keeps apply disabled", async () => {
    vi.mocked(importTagsCsv).mockResolvedValue(REFUSED);
    render(<CatalogueCsvPanel t={t} />);
    chooseFile();
    fireEvent.click(screen.getByText("catalogueCsv.check"));
    expect(await screen.findByText("column is not a tag field of the schema")).toBeInTheDocument();
    expect(screen.getByText("catalogueCsv.errors")).toBeInTheDocument();
    expect(screen.getByText("catalogueCsv.apply")).toBeDisabled();
  });

  it("enables apply after a clean dry run", async () => {
    vi.mocked(importTagsCsv).mockResolvedValue(CLEAN);
    render(<CatalogueCsvPanel t={t} />);
    chooseFile();
    fireEvent.click(screen.getByText("catalogueCsv.check"));
    expect(await screen.findByText('catalogueCsv.ok {"tags":2}')).toBeInTheDocument();
    expect(screen.getByText("catalogueCsv.apply")).toBeEnabled();
  });

  it("applies the checked CSV for real and reports the import", async () => {
    vi.mocked(importTagsCsv)
      .mockResolvedValueOnce(CLEAN)
      .mockResolvedValueOnce(SAVED);
    const onImported = vi.fn();
    render(<CatalogueCsvPanel t={t} onImported={onImported} />);
    chooseFile();
    fireEvent.click(screen.getByText("catalogueCsv.check"));
    await screen.findByText('catalogueCsv.ok {"tags":2}');
    fireEvent.click(screen.getByText("catalogueCsv.apply"));
    await waitFor(() => expect(importTagsCsv).toHaveBeenLastCalledWith(CSV_TEXT, false));
    expect(await screen.findByText('catalogueCsv.applied {"tags":2}')).toBeInTheDocument();
    expect(onImported).toHaveBeenCalledTimes(1);
  });

  it("shows an alert when the server fails", async () => {
    vi.mocked(importTagsCsv).mockRejectedValue(new Error("site is missing"));
    render(<CatalogueCsvPanel t={t} />);
    chooseFile();
    fireEvent.click(screen.getByText("catalogueCsv.check"));
    expect(await screen.findByRole("alert")).toHaveTextContent("site is missing");
  });
});

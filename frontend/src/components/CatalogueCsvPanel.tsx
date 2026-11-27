// frontend/src/components/CatalogueCsvPanel.tsx
/**
 * Catalogue > CSV (issue #144): download the site's tags as a CSV file, check an edited
 * file with a dry run, and apply it once the dry run is clean.
 * A refused import is not a crash: the server answers 422 and the dry run resolves with
 * its row errors, which the panel shows as a row/column/message table.
 */

import { useState } from "react";
import { downloadTagsCsv, importTagsCsv, type CsvImportResult, type CsvRowError } from "../catalogueCsvApi";
import type { Translate } from "../findings";

export interface CatalogueCsvPanelProps {
  t: Translate;
  onImported?: () => void;
}

/** The file name the site tags CSV is saved under. */
const DOWNLOAD_FILE_NAME = "site-tags.csv";
/** The media type the downloaded CSV blob is labelled with. */
const CSV_BLOB_TYPE = "text/csv;charset=utf-8";
/** The BOM in front of the text tells Excel the CSV is UTF-8. */
const UTF8_BYTE_ORDER_MARK = "\uFEFF";

/** Save a CSV string as a download through a temporary link. */
function saveCsv(csv: string): void {
  const blob = new Blob([UTF8_BYTE_ORDER_MARK + csv], { type: CSV_BLOB_TYPE });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = DOWNLOAD_FILE_NAME;
  link.click();
  URL.revokeObjectURL(url);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** The problems a refused CSV earned; every row is one to fix before applying. */
function RowErrors({ errors, t }: { errors: CsvRowError[]; t: Translate }) {
  return (
    <table aria-label={t("catalogueCsv.errors")}>
      <caption>{t("catalogueCsv.errors")}</caption>
      <thead>
        <tr>
          <th scope="col">row</th>
          <th scope="col">column</th>
          <th scope="col">message</th>
        </tr>
      </thead>
      <tbody>
        {errors.map((problem, index) => (
          <tr key={index}>
            <td>{problem.row}</td>
            <td>{problem.column}</td>
            <td>{problem.message}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** The catalogue CSV panel: download the site tags, check the CSV, apply it. */
export function CatalogueCsvPanel({ t, onImported }: CatalogueCsvPanelProps) {
  const [file, setFile] = useState<File | null>(null);
  const [dryRun, setDryRun] = useState<CsvImportResult | null>(null);
  const [appliedTags, setAppliedTags] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Apply is two-step: only a CSV that passed a dry run without errors may be saved.
  const cleanDryRun = dryRun !== null && dryRun.errors.length === 0;

  const run = async (action: () => Promise<void>): Promise<void> => {
    setBusy(true);
    setError(null);
    setAppliedTags(null);
    try {
      await action();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  // The file is read at click time so the check and apply always use the current bytes.
  const readCsv = async (): Promise<string | null> => {
    if (file === null) return null;
    return file.text();
  };

  const download = () => run(async () => {
    saveCsv(await downloadTagsCsv());
  });

  const check = () => run(async () => {
    const csv = await readCsv();
    if (csv === null) return;
    setDryRun(await importTagsCsv(csv, true));
  });

  const apply = () => run(async () => {
    const csv = await readCsv();
    if (csv === null) return;
    const result = await importTagsCsv(csv, false);
    setDryRun(result);
    if (result.errors.length === 0) {
      setAppliedTags(result.tags);
      onImported?.();
    }
  });

  // Choosing a fresh file invalidates any report from the previous one.
  const choose = (chosen: File | null) => {
    setFile(chosen);
    setDryRun(null);
    setAppliedTags(null);
  };

  return (
    <section aria-label={t("catalogueCsv.title")}>
      <h2>{t("catalogueCsv.title")}</h2>
      <button type="button" disabled={busy} onClick={() => void download()}>{t("catalogueCsv.download")}</button>
      <div className="field">
        <label className="field-label" htmlFor="catalogue-csv-file">{t("catalogueCsv.file")}</label>
        <input id="catalogue-csv-file" className="field-input" type="file" accept=".csv,text/csv"
          onChange={(event) => choose(event.target.files?.[0] ?? null)} />
      </div>
      <button type="button" disabled={busy || file === null} onClick={() => void check()}>{t("catalogueCsv.check")}</button>
      <button type="button" disabled={busy || !cleanDryRun} onClick={() => void apply()}>{t("catalogueCsv.apply")}</button>
      {dryRun !== null && dryRun.errors.length === 0 && (
        <p className="notice" role="status">{t("catalogueCsv.ok", { tags: dryRun.tags })}</p>
      )}
      {dryRun !== null && dryRun.errors.length > 0 && <RowErrors errors={dryRun.errors} t={t} />}
      {appliedTags !== null && (
        <p className="notice" role="status">{t("catalogueCsv.applied", { tags: appliedTags })}</p>
      )}
      {error !== null && <div className="notice notice-warning" role="alert"><p>{error}</p></div>}
    </section>
  );
}

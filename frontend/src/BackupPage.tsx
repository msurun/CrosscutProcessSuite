// frontend/src/BackupPage.tsx
/**
 * Administration > Backup (issue #167): download a configuration backup (no history, no secrets),
 * upload one, read the dry-run report, and restore it after an explicit confirmation.
 */

import { useState } from "react";
import { downloadBackup, inspectBackup, restoreBackup, type BackupReport, type MustReenter } from "./backupApi";
import { useCan } from "./AuthContext";
import type { Translate } from "./findings";

export interface BackupPageProps {
  t: Translate;
}

const EXCLUDED_KEYS = ["datasets", "runtime", "uploads", "queues", "secrets"] as const;

/** Save a blob through a temporary link, the way a browser download starts. */
function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function ReenterList({ items, t }: { items: MustReenter[]; t: Translate }) {
  if (items.length === 0) return null;
  return (
    <section aria-label={t("backup.reenter.title")}>
      <h4>{t("backup.reenter.title")}</h4>
      <ul>
        {items.map((item, i) => (
          <li key={`${item.kind}-${item.ref ?? i}`}>
            {item.kind === "source_secret"
              ? t("backup.reenter.source", { source: item.source ?? "", ref: item.ref ?? "" })
              : t("backup.reenter.gatewayKey")}
          </li>
        ))}
      </ul>
    </section>
  );
}

function ReportView({ report, t }: { report: BackupReport; t: Translate }) {
  return (
    <section aria-label={t("backup.report.title")} data-testid="backup-report">
      <h3>{t("backup.report.title")}</h3>
      {report.ok ? (
        <p className="status-chip status-chip--ok">{t("backup.report.ok", { created: report.created_utc })}</p>
      ) : (
        <div className="notice notice-warning" role="alert">
          <p>{t("backup.report.refused")}</p>
          <ul>{report.problems.map((p) => <li key={p}>{p}</li>)}</ul>
        </div>
      )}
      {report.ok && (
        <table aria-label={t("backup.report.changes")}>
          <thead><tr><th scope="col">{t("backup.report.path")}</th><th scope="col">{t("backup.report.action")}</th></tr></thead>
          <tbody>
            {report.changes.map((c) => (
              <tr key={c.path}><td>{c.path}</td><td>{t(`backup.action.${c.action}`)}</td></tr>
            ))}
          </tbody>
        </table>
      )}
      {report.ok && <ReenterList items={report.must_reenter} t={t} />}
    </section>
  );
}

function ScopeInfo({ t }: { t: Translate }) {
  return (
    <section aria-label={t("backup.scope.title")}>
      <h2>{t("backup.scope.title")}</h2>
      <p>{t("backup.scope.included")}</p>
      <p>{t("backup.scope.excluded")}</p>
      <ul>{EXCLUDED_KEYS.map((key) => <li key={key}>{t(`backup.excluded.${key}`)}</li>)}</ul>
    </section>
  );
}

function useBackup(t: Translate) {
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<BackupReport | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (action: () => Promise<void>): Promise<void> => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await action();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const download = () => run(async () => {
    const { blob, filename } = await downloadBackup();
    saveBlob(blob, filename);
    setMessage(t("backup.downloaded", { name: filename }));
  });
  const check = () => run(async () => {
    if (file) setReport(await inspectBackup(file));
    setConfirmed(false);
  });
  const restore = () => run(async () => {
    if (!file || !report) return;
    await restoreBackup(file, report.archive_sha256);
    setMessage(t("backup.restored"));
    setReport(null);
    setConfirmed(false);
  });
  const choose = (chosen: File | null) => {
    setFile(chosen);
    setReport(null);
    setConfirmed(false);
  };
  return { file, report, confirmed, setConfirmed, busy, message, error, download, check, restore, choose };
}

/** The backup and restore page for administrators. */
export function BackupPage({ t }: BackupPageProps) {
  const { allowed } = useCan("users.manage");
  const b = useBackup(t);
  if (!allowed) {
    return <div className="notice notice-warning" role="alert"><p>{t("backup.denied")}</p></div>;
  }
  return (
    <div className="backup-page" style={{ maxWidth: 960, margin: "20px auto", padding: "0 16px", boxSizing: "border-box" }}>
      <h1>{t("backup.title")}</h1>
      <p>{t("backup.subtitle")}</p>
      {b.error && <div className="notice notice-warning" role="alert"><p style={{ whiteSpace: "pre-line" }}>{b.error}</p></div>}
      {b.message && <div className="notice" role="status"><p>{b.message}</p></div>}
      <ScopeInfo t={t} />
      <section aria-label={t("backup.download.title")}>
        <h2>{t("backup.download.title")}</h2>
        <p>{t("backup.download.hint")}</p>
        <button type="button" disabled={b.busy} onClick={() => void b.download()}>{t("backup.download.button")}</button>
      </section>
      <section aria-label={t("backup.restore.title")}>
        <h2>{t("backup.restore.title")}</h2>
        <div className="field">
          <label className="field-label" htmlFor="backup-file">{t("backup.restore.file")}</label>
          <input id="backup-file" className="field-input" type="file" accept=".zip,application/zip"
            onChange={(event) => b.choose(event.target.files?.[0] ?? null)} />
        </div>
        <button type="button" disabled={b.busy || !b.file} onClick={() => void b.check()}>{t("backup.restore.check")}</button>
        {b.report && <ReportView report={b.report} t={t} />}
        {b.report?.ok && (
          <div>
            <label>
              <input type="checkbox" checked={b.confirmed} onChange={(e) => b.setConfirmed(e.target.checked)} />
              {" "}{t("backup.restore.confirm")}
            </label>
            <div>
              <button type="button" disabled={b.busy || !b.confirmed} onClick={() => void b.restore()}>{t("backup.restore.button")}</button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

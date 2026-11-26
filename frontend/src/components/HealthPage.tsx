// frontend/src/components/HealthPage.tsx
/**
 * Administration > Health (#170): one read-only table of the runtime, its jobs, the gateway, the
 * liveness the gateway sees, the audit writes, the data disk and the package versions, each with
 * ok / warning / error and a reason. Polls every 10 s; "Refresh" reads now. Users who hold
 * users.manage also get the log export (a zip of the logs of a time range, scrubbed of secrets).
 */

import { useCallback, useEffect, useState } from "react";
import { useCan } from "../AuthContext";
import type { Translate } from "../findings";
import {
  fetchHealth,
  fetchLogExport,
  saveBlob,
  type HealthItem,
  type HealthReport,
} from "../healthApi";
import { DisabledReason } from "./DisabledReason";
import { detailLines, itemLabel, itemReason, levelOf } from "./healthFormat";
import { StatusChip } from "./StatusChip";

/** How often the page re-reads the report, in milliseconds. */
const POLL_INTERVAL_MS = 10_000;
const DAY_MS = 24 * 3600 * 1000;
const GROUPS = ["runtime", "jobs", "gateway", "liveness", "audit", "system"] as const;

export interface HealthPageProps {
  t: Translate;
}

/** `datetime-local` value (local time, minutes) of an instant. */
function localInput(moment: Date): string {
  const shifted = new Date(moment.getTime() - moment.getTimezoneOffset() * 60_000);
  return shifted.toISOString().slice(0, 16);
}

const errorText = (error: unknown): string => (error instanceof Error ? error.message : String(error));

function HealthRow({ item, t }: { item: HealthItem; t: Translate }) {
  const lines = detailLines(item, t);
  return (
    <tr data-testid={`health-item-${item.id}`}>
      <th scope="row">{itemLabel(item, t)}</th>
      <td><StatusChip level={levelOf(item.status)} label={t(`health.status.${item.status}`)} /></td>
      <td>{itemReason(item, t)}</td>
      <td>{lines.map((line) => <div key={line} className="hint">{line}</div>)}</td>
    </tr>
  );
}

function HealthGroup({ group, items, t }: { group: string; items: HealthItem[]; t: Translate }) {
  return (
    <section data-testid={`health-group-${group}`}>
      <h2>{t(`health.group.${group}`)}</h2>
      <div className="table-scroll" tabIndex={0} role="region" aria-label={t(`health.group.${group}`)}>
        <table className="loops-table">
          <caption className="hint">{t(`health.group.${group}`)}</caption>
          <thead>
            <tr>
              <th scope="col">{t("health.col.item")}</th>
              <th scope="col">{t("health.col.status")}</th>
              <th scope="col">{t("health.col.reason")}</th>
              <th scope="col">{t("health.col.details")}</th>
            </tr>
          </thead>
          <tbody>{items.map((item) => <HealthRow key={item.id} item={item} t={t} />)}</tbody>
        </table>
      </div>
    </section>
  );
}

interface ExportProps {
  t: Translate;
}

/** Range fields and the export button; only rendered for the whole page, enabled with users.manage. */
function LogExport({ t }: ExportProps) {
  const can = useCan("users.manage");
  const [start, setStart] = useState(() => localInput(new Date(Date.now() - DAY_MS)));
  const [end, setEnd] = useState(() => localInput(new Date()));
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const download = () => {
    setBusy(true);
    setProblem(null);
    const iso = (value: string) => (value === "" ? "" : new Date(value).toISOString());
    fetchLogExport(iso(start), iso(end))
      .then((blob) => saveBlob(blob, `crosscut-logs-${new Date().toISOString().slice(0, 10)}.zip`))
      .catch((error: unknown) => setProblem(errorText(error)))
      .finally(() => setBusy(false));
  };

  return (
    <section className="notice" data-testid="health-export">
      <h2>{t("health.export.title")}</h2>
      <p className="hint">{t("health.export.hint")}</p>
      <div className="knowledge-fields">
        <label className="field">
          <span className="field-label">{t("health.export.from")}</span>
          <input className="field-input" type="datetime-local" data-testid="health-export-start" value={start} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label className="field">
          <span className="field-label">{t("health.export.to")}</span>
          <input className="field-input" type="datetime-local" data-testid="health-export-end" value={end} onChange={(e) => setEnd(e.target.value)} />
        </label>
      </div>
      <div className="toolbar">
        <DisabledReason disabled={!can.allowed} reason={can.reason} requiredRole={can.requiredRole} t={t}>
          <button type="button" data-testid="health-export-button" onClick={download} disabled={busy && can.allowed}>
            {busy ? t("health.export.busy") : t("health.export.button")}
          </button>
        </DisabledReason>
      </div>
      {problem !== null && <p className="notice notice-warning" role="alert" data-testid="health-export-error">{problem}</p>}
    </section>
  );
}

export function HealthPage({ t }: HealthPageProps) {
  const [report, setReport] = useState<HealthReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    fetchHealth()
      .then((next) => {
        setReport(next);
        setError(null);
      })
      .catch((err: unknown) => setError(errorText(err)));
  }, []);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  return (
    <div data-testid="health-page">
      <div className="banner">
        <h1>{t("health.title")}</h1>
        <p className="hint">{t("health.subtitle")}</p>
      </div>
      <div className="toolbar">
        <button type="button" data-testid="health-refresh" onClick={refresh}>{t("health.refresh")}</button>
        {report !== null && (
          <span data-testid="health-overall">
            <StatusChip level={levelOf(report.status)} label={t(`health.overall.${report.status}`)} />
          </span>
        )}
        {report !== null && <span className="hint">{t("health.generated", { time: report.generated_utc })}</span>}
      </div>
      {error !== null && (
        <div className="notice notice-warning" role="alert" data-testid="health-error">
          <p>{t("health.error", { reason: error })}</p>
        </div>
      )}
      {report !== null && GROUPS.map((group) => {
        const items = report.items.filter((item) => item.group === group);
        return items.length > 0 ? <HealthGroup key={group} group={group} items={items} t={t} /> : null;
      })}
      <LogExport t={t} />
    </div>
  );
}

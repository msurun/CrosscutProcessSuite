// frontend/src/RuntimePage.tsx
/**
 * Runtime view (Phase 1, #44): service health, the jobs the runtime service runs
 * (stored configuration merged with their live state), start/stop/delete actions,
 * a new-job form, and the tail of the runtime log.
 * Polls GET /runtime/status every 5 s while mounted; nothing here writes to a plant.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createRuntimeJob,
  deleteRuntimeJob,
  fetchRuntimeJobs,
  fetchRuntimeLog,
  fetchRuntimeStatus,
  startRuntimeJob,
  stopRuntimeJob,
  type RuntimeJob,
  type RuntimeJobSummary,
  type RuntimeServiceStatus,
} from "./api";
import type { Translate } from "./findings";

/** How often the page re-reads the runtime status, in milliseconds. */
const POLL_INTERVAL_MS = 5000;
/** How many log lines are shown at once, and how many "Load more" adds. */
const LOG_PAGE_SIZE = 50;

export interface RuntimePageProps {
  t: Translate;
}

/** The "new job" form while the user types it; numbers stay text until sent. */
interface NewJobForm {
  id: string;
  kind: RuntimeJob["kind"];
  source: string;
  targets: string;
  periodS: string;
  windowS: string;
}

const EMPTY_FORM: NewJobForm = { id: "", kind: "loop_kpi", source: "", targets: "", periodS: "60", windowS: "3600" };

/** The chip colour of a job state; unknown states stay neutral. */
export function jobStateChipClass(state: string): string {
  if (state === "error" || state === "failed") return "status-chip status-chip--problem";
  if (state === "running" || state === "ok") return "status-chip status-chip--ok";
  return "status-chip status-chip--unused";
}

/** One row of the jobs table: the live state merged with the stored job, when known. */
interface JobRow {
  summary: RuntimeJobSummary;
  config: RuntimeJob | undefined;
}

/** The KPI cell of a loop_kpi job: per loop id the classification and the Harris index. */
function KpiCell({ kpi, t }: { kpi: RuntimeJobSummary["kpi"]; t: Translate }) {
  const none = t("runtime.none");
  if (kpi === null) return <span className="hint">{none}</span>;
  return (
    <>
      {Object.entries(kpi).map(([loopId, one]) => (
        <div key={loopId} className="hint">
          {loopId}: {one.classification ?? none} · {t("runtime.kpi.harris")} {one.harris_index ?? none}
        </div>
      ))}
    </>
  );
}

export function RuntimePage({ t }: RuntimePageProps) {
  const [service, setService] = useState<RuntimeServiceStatus | null>(null);
  const [summaries, setSummaries] = useState<RuntimeJobSummary[]>([]);
  const [jobs, setJobs] = useState<RuntimeJob[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [logLimit, setLogLimit] = useState(LOG_PAGE_SIZE);
  const [form, setForm] = useState<NewJobForm>(EMPTY_FORM);
  const [problems, setProblems] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);

  const errorMessage = (err: unknown): string => (err instanceof Error ? err.message : String(err));

  const pollStatus = useCallback(() => {
    fetchRuntimeStatus()
      .then((status) => {
        setService(status.service);
        setSummaries(status.jobs);
        setError(null);
      })
      .catch((err: unknown) => setError(errorMessage(err)));
  }, []);

  const loadJobs = useCallback(() => {
    fetchRuntimeJobs()
      .then((document) => setJobs(document.jobs))
      .catch((err: unknown) => setError(errorMessage(err)));
  }, []);

  /** Refresh button and the answer of every mutation: re-read status and the jobs document. */
  const refresh = useCallback(() => {
    pollStatus();
    loadJobs();
  }, [pollStatus, loadJobs]);

  // Read the status and the jobs once, then poll the status while the page is mounted.
  useEffect(() => {
    refresh();
    const timer = window.setInterval(pollStatus, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [refresh, pollStatus]);

  const loadLog = useCallback(() => {
    fetchRuntimeLog(logLimit)
      .then((log) => setLogLines(log.lines))
      .catch(() => undefined); // The log is secondary: a failure just keeps the old lines.
  }, [logLimit]);

  useEffect(() => {
    loadLog();
  }, [loadLog]);

  const jobConfig = useMemo(() => new Map(jobs.map((job) => [job.id, job])), [jobs]);
  const rows: JobRow[] = summaries.map((summary) => ({ summary, config: jobConfig.get(summary.id) }));

  const handleStart = useCallback(
    (jobId: string) => {
      startRuntimeJob(jobId)
        .catch((err: unknown) => setError(errorMessage(err)))
        .finally(() => refresh());
    },
    [refresh],
  );

  const handleStop = useCallback(
    (jobId: string) => {
      stopRuntimeJob(jobId)
        .catch((err: unknown) => setError(errorMessage(err)))
        .finally(() => refresh());
    },
    [refresh],
  );

  const handleDelete = useCallback(
    (jobId: string) => {
      deleteRuntimeJob(jobId)
        .catch((err: unknown) => setError(errorMessage(err)))
        .finally(() => refresh());
    },
    [refresh],
  );

  function handleField(field: keyof NewJobForm, value: string) {
    setForm((previous) => ({ ...previous, [field]: field === "kind" ? (value as NewJobForm["kind"]) : value }));
    setProblems([]);
  }

  async function handleCreate() {
    if (creating) return;
    const targets = form.targets.split(",").map((entry) => entry.trim()).filter((entry) => entry !== "");
    const job: RuntimeJob = {
      id: form.id.trim(),
      kind: form.kind,
      source: form.source.trim(),
      period_s: Number(form.periodS),
      window_s: Number(form.windowS),
      enabled: true,
    };
    if (form.kind === "loop_kpi") job.loops = targets;
    else job.tags = targets;

    setCreating(true);
    setProblems([]);
    try {
      await createRuntimeJob(job);
      setForm({ ...EMPTY_FORM, kind: form.kind });
      refresh();
    } catch (err) {
      const message = errorMessage(err);
      // A multi-line message is a list of validation problems; one line per entry.
      setProblems(message.includes("\n") ? message.split("\n") : [message]);
    } finally {
      setCreating(false);
    }
  }

  const serviceRunning = service !== null && service.running;
  const serviceUpdated = service?.updated_at_utc ?? null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }} data-testid="runtime-page">
      <div className="banner">
        <h2>{t("runtime.title")}</h2>
        <p className="hint">{t("runtime.subtitle")}</p>
        <div className="toolbar">
          <span>{t("runtime.service")}:</span>
          <span
            className={serviceRunning ? "status-chip status-chip--ok" : "status-chip status-chip--problem"}
            role="status"
            data-testid="runtime-service-status"
          >
            {serviceRunning ? t("runtime.service.running") : t("runtime.service.stopped")}
          </span>
          <span className="hint">
            {serviceUpdated === null ? t("runtime.service.never") : t("runtime.service.updated", { time: serviceUpdated })}
          </span>
          <button type="button" onClick={refresh}>
            {t("runtime.refresh")}
          </button>
        </div>
      </div>

      {error !== null && (
        <div className="notice notice-warning" role="alert">
          <p>{t("runtime.error", { reason: error })}</p>
        </div>
      )}

      <section>
        <h3>{t("runtime.jobs.title")}</h3>
        {rows.length === 0 ? (
          <p className="hint">{t("runtime.jobs.empty")}</p>
        ) : (
          <div className="table-scroll">
            <table className="loops-table">
              <thead>
                <tr>
                  <th>{t("runtime.table.id")}</th>
                  <th>{t("runtime.table.kind")}</th>
                  <th>{t("runtime.table.source")}</th>
                  <th>{t("runtime.table.targets")}</th>
                  <th>{t("runtime.table.periodS")}</th>
                  <th>{t("runtime.table.windowS")}</th>
                  <th>{t("runtime.table.enabled")}</th>
                  <th>{t("runtime.table.status")}</th>
                  <th>{t("runtime.table.lastRun")}</th>
                  <th>{t("runtime.table.error")}</th>
                  <th>{t("runtime.table.samples")}</th>
                  <th>{t("runtime.table.kpi")}</th>
                  <th>{t("runtime.table.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ summary, config }) => {
                  const targets = summary.kind === "anomaly_scan" ? config?.tags : config?.loops;
                  const none = t("runtime.none");
                  return (
                    <tr key={summary.id} data-testid={`runtime-job-${summary.id}`}>
                      <td>{summary.id}</td>
                      <td>{t(`runtime.kind.${summary.kind}`)}</td>
                      <td>{summary.source}</td>
                      <td>{targets === undefined || targets.length === 0 ? none : targets.join(", ")}</td>
                      <td>{config?.period_s ?? none}</td>
                      <td>{config?.window_s ?? none}</td>
                      <td>{summary.enabled ? t("runtime.enabled") : t("runtime.disabled")}</td>
                      <td>
                        <span className={jobStateChipClass(summary.status)}>{summary.status}</span>
                      </td>
                      <td>{summary.last_run_utc ?? none}</td>
                      <td>{summary.error ?? ""}</td>
                      <td>{summary.samples}</td>
                      <td>
                        <KpiCell kpi={summary.kpi} t={t} />
                      </td>
                      <td>
                        <span className="toolbar">
                          {summary.enabled ? (
                            <button type="button" data-testid={`runtime-stop-${summary.id}`} onClick={() => handleStop(summary.id)}>
                              {t("runtime.stop")}
                            </button>
                          ) : (
                            <button type="button" data-testid={`runtime-start-${summary.id}`} onClick={() => handleStart(summary.id)}>
                              {t("runtime.start")}
                            </button>
                          )}
                          <button type="button" data-testid={`runtime-delete-${summary.id}`} onClick={() => handleDelete(summary.id)}>
                            {t("runtime.delete")}
                          </button>
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="notice">
        <h3>{t("runtime.newJob")}</h3>
        <div className="knowledge-fields">
          <label className="field">
            <span className="field-label">{t("runtime.field.id")}</span>
            <input className="field-input" data-testid="runtime-form-id" value={form.id} onChange={(event) => handleField("id", event.target.value)} />
          </label>
          <label className="field">
            <span className="field-label">{t("runtime.field.kind")}</span>
            <select
              className="field-input"
              data-testid="runtime-form-kind"
              value={form.kind}
              onChange={(event) => handleField("kind", event.target.value)}
            >
              <option value="loop_kpi">{t("runtime.kind.loop_kpi")}</option>
              <option value="anomaly_scan">{t("runtime.kind.anomaly_scan")}</option>
            </select>
          </label>
          <label className="field">
            <span className="field-label">{t("runtime.field.source")}</span>
            <input className="field-input" data-testid="runtime-form-source" value={form.source} onChange={(event) => handleField("source", event.target.value)} />
          </label>
          <label className="field">
            <span className="field-label">{form.kind === "loop_kpi" ? t("runtime.field.loops") : t("runtime.field.tags")}</span>
            <input className="field-input" data-testid="runtime-form-targets" value={form.targets} onChange={(event) => handleField("targets", event.target.value)} />
          </label>
          <label className="field">
            <span className="field-label">{t("runtime.field.periodS")}</span>
            <input className="field-input" type="number" data-testid="runtime-form-period" value={form.periodS} onChange={(event) => handleField("periodS", event.target.value)} />
          </label>
          <label className="field">
            <span className="field-label">{t("runtime.field.windowS")}</span>
            <input className="field-input" type="number" data-testid="runtime-form-window" value={form.windowS} onChange={(event) => handleField("windowS", event.target.value)} />
          </label>
        </div>
        <div className="toolbar">
          <button type="button" data-testid="runtime-create" onClick={handleCreate} disabled={creating}>
            {creating ? t("runtime.creating") : t("runtime.create")}
          </button>
        </div>
        {problems.length > 0 && (
          <div role="alert" data-testid="runtime-problems">
            <p className="status status-error">{t("runtime.problems")}</p>
            <ul className="status status-error">
              {problems.map((line, index) => (
                <li key={index}>{line}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section>
        <h3>{t("runtime.log.title")}</h3>
        <div className="toolbar">
          <button type="button" onClick={loadLog}>
            {t("runtime.log.refresh")}
          </button>
          {logLines.length >= logLimit && (
            <button type="button" data-testid="runtime-log-more" onClick={() => setLogLimit((limit) => limit + LOG_PAGE_SIZE)}>
              {t("runtime.log.loadMore")}
            </button>
          )}
        </div>
        {logLines.length === 0 ? (
          <p className="hint">{t("runtime.log.empty")}</p>
        ) : (
          <div className="notice">
            <pre className="hint" data-testid="runtime-log">
              {logLines.join("\n")}
            </pre>
          </div>
        )}
      </section>
    </div>
  );
}

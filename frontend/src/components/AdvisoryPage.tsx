// Advisory page (module 2): pick a supervisor, read its configuration, ask for advice, replay a
// record and keep a decision log. Advisory only: nothing here writes to a plant; a banner says so.
import type { Translate } from "../findings";
import { AdvisoryConfigSummary } from "./AdvisoryConfigSummary";
import { AdvisoryLog } from "./AdvisoryLog";
import { AdvisoryRun } from "./AdvisoryRun";
import { useAdvisoryLog, useSupervisors, type SupervisorsState } from "./AdvisoryState";

/** The persistent banner: the page only advises and records decisions. */
export function AdvisoryBanner({ t }: { t: Translate }) {
  return <p className="notice banner-warning" role="note">{t("advisory.banner")}</p>;
}

/** Supervisor select, or the empty state with the "Load example" button. */
function SupervisorPicker({ state, t }: { state: SupervisorsState; t: Translate }) {
  if (!state.loaded) return <p className="status">{t("trends.loading")}</p>;
  if (state.ids.length === 0) {
    return (
      <div className="notice" data-testid="advisory-empty">
        <p>{t("advisory.empty")}</p>
        <button type="button" className="filter-chip" onClick={() => void state.loadExample()}>{t("advisory.loadExample")}</button>
      </div>
    );
  }
  return (
    <label className="field">
      <span className="field-label">{t("advisory.supervisor")}</span>
      <select className="field-input" value={state.selectedId} onChange={(event) => state.select(event.target.value)}>
        {state.ids.map((id) => <option key={id} value={id}>{id}</option>)}
      </select>
    </label>
  );
}

/** Everything that needs a chosen supervisor. */
function SupervisorBody({ state, datasetId, t }: { state: SupervisorsState; datasetId: string; t: Translate }) {
  const { log, error, reload } = useAdvisoryLog(state.selectedId);
  if (state.selectedId === "") return null;
  return (
    <>
      {state.config !== null && <AdvisoryConfigSummary config={state.config} t={t} />}
      <AdvisoryRun datasetId={datasetId} supervisorId={state.selectedId} t={t} onRecorded={reload} />
      <AdvisoryLog supervisorId={state.selectedId} log={log} error={error} t={t} onChanged={reload} />
    </>
  );
}

/** The Advisory view; `datasetId` is the dataset chosen in the app (empty when none). */
export function AdvisoryPage({ datasetId, t }: { datasetId: string; t: Translate }) {
  const state = useSupervisors();
  return (
    <section>
      <header className="toolbar">
        <h2>{t("advisory.title")}</h2>
        <span className="badge">{t("advisory.mode.advisory")}</span>
      </header>
      <AdvisoryBanner t={t} />
      {state.error !== null && <p className="status status-error" role="alert">{t("trends.error", { reason: state.error })}</p>}
      <SupervisorPicker state={state} t={t} />
      <SupervisorBody state={state} datasetId={datasetId} t={t} />
    </section>
  );
}

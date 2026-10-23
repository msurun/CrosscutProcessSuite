// Anomalies page: pick a PCA anomaly detector, read its configuration, fit it on a stretch of
// normal operation and scan a window for T2 / SPE events. Advisory only: nothing here writes to a
// plant, and two notes say so and how far the alarm limits can be trusted.
import type { Translate } from "../findings";
import { AnomalyConfigSummary } from "./AnomalyConfigSummary";
import { AnomalyFit } from "./AnomalyFit";
import { AnomalyModel } from "./AnomalyModel";
import { AnomalyScan } from "./AnomalyScan";
import { useAnomalies, useAnomalyModel, type AnomaliesState } from "./AnomalyState";

/** The two persistent notes: advisory only, and the statistical nature of the limits. */
export function AnomalyNotes({ t }: { t: Translate }) {
  return (
    <>
      <p className="notice banner-warning" role="note">{t("anomaly.banner")}</p>
      <p className="notice" role="note">{t("anomaly.statNote")}</p>
    </>
  );
}

/** Detector select, or the empty state with the "Load example" button. */
function DetectorPicker({ state, t }: { state: AnomaliesState; t: Translate }) {
  if (!state.loaded) return <p className="status">{t("trends.loading")}</p>;
  if (state.ids.length === 0) {
    return (
      <div className="notice" data-testid="anomaly-empty">
        <p>{t("anomaly.empty")}</p>
        <button type="button" className="filter-chip" onClick={() => void state.loadExample()}>{t("anomaly.loadExample")}</button>
      </div>
    );
  }
  return (
    <label className="field">
      <span className="field-label">{t("anomaly.detector")}</span>
      <select className="field-input" value={state.selectedId} onChange={(event) => state.select(event.target.value)}>
        {state.ids.map((id) => <option key={id} value={id}>{id}</option>)}
      </select>
    </label>
  );
}

interface BodyProps {
  state: AnomaliesState;
  datasetId: string;
  recordHours: number | null;
  t: Translate;
}

/** Everything that needs a chosen detector: config, fit, model and scan. */
function DetectorBody({ state, datasetId, recordHours, t }: BodyProps) {
  const stored = useAnomalyModel(state.selectedId, t);
  if (state.selectedId === "") return null;
  return (
    <>
      {state.config !== null && <AnomalyConfigSummary config={state.config} t={t} />}
      <AnomalyFit key={`${state.selectedId}|${datasetId}`} datasetId={datasetId} detectorId={state.selectedId} recordHours={recordHours} t={t} onFitted={stored.set} />
      {stored.error !== null && <p className="status status-error" role="alert">{stored.error}</p>}
      {stored.loaded && <AnomalyModel model={stored.model} t={t} />}
      {stored.model !== null && (
        <AnomalyScan key={`${state.selectedId}|${datasetId}|${stored.model.sha256}`} datasetId={datasetId} detectorId={state.selectedId} recordHours={recordHours} t={t} />
      )}
    </>
  );
}

/** The Anomalies view; `datasetId` is the dataset chosen in the app, `recordHours` its length. */
export function AnomalyPage({ datasetId, recordHours, t }: { datasetId: string; recordHours: number | null; t: Translate }) {
  const state = useAnomalies(t);
  return (
    <section>
      <header className="toolbar">
        <h2>{t("anomaly.title")}</h2>
        <span className="badge">{t("anomaly.mode.advisory")}</span>
      </header>
      <AnomalyNotes t={t} />
      {state.error !== null && <p className="status status-error" role="alert">{t("trends.error", { reason: state.error })}</p>}
      <DetectorPicker state={state} t={t} />
      <DetectorBody state={state} datasetId={datasetId} recordHours={recordHours} t={t} />
    </section>
  );
}

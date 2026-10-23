// Soft sensor page: pick a PLS soft sensor, read its configuration, upload the laboratory results,
// fit on the results that were available before a train end and run the model over a window. Advisory
// only: nothing here writes to a plant, and two notes say so and how far the estimate can be trusted.
import type { Translate } from "../findings";
import { DEFAULT_LAB_DELAY_S } from "../softsensor";
import { SoftSensorConfigSummary } from "./SoftSensorConfigSummary";
import { SoftSensorFit } from "./SoftSensorFit";
import { SoftSensorLab } from "./SoftSensorLab";
import { SoftSensorModel } from "./SoftSensorModel";
import { SoftSensorRun } from "./SoftSensorRun";
import { useSoftLab, useSoftModel, useSoftSensors, type SoftSensorsState } from "./SoftSensorState";

/** The two persistent notes: advisory only, and what the estimate is and how far it can be trusted. */
export function SoftSensorNotes({ t }: { t: Translate }) {
  return (
    <>
      <p className="notice banner-warning" role="note">{t("soft.banner")}</p>
      <p className="notice" role="note">{t("soft.note")}</p>
    </>
  );
}

/** Sensor select, or the empty state with the "Load example" button. */
function SensorPicker({ state, t }: { state: SoftSensorsState; t: Translate }) {
  if (!state.loaded) return <p className="status">{t("trends.loading")}</p>;
  if (state.ids.length === 0) {
    return (
      <div className="notice" data-testid="soft-empty">
        <p>{t("soft.empty")}</p>
        <button type="button" className="filter-chip" onClick={() => void state.loadExample()}>{t("soft.loadExample")}</button>
      </div>
    );
  }
  return (
    <label className="field">
      <span className="field-label">{t("soft.sensor")}</span>
      <select className="field-input" value={state.selectedId} onChange={(event) => state.select(event.target.value)}>
        {state.ids.map((id) => <option key={id} value={id}>{id}</option>)}
      </select>
    </label>
  );
}

interface BodyProps {
  state: SoftSensorsState;
  datasetId: string;
  recordHours: number | null;
  startUtc: string;
  t: Translate;
}

/** Everything that needs a chosen sensor: config, lab results, fit, model and run. */
function SensorBody({ state, datasetId, recordHours, startUtc, t }: BodyProps) {
  const lab = useSoftLab(state.selectedId, t);
  const model = useSoftModel(state.selectedId, t);
  if (state.selectedId === "" || state.config === null) return null;
  const labDelayS = state.config.lab_delay_s ?? DEFAULT_LAB_DELAY_S;
  const key = `${state.selectedId}|${datasetId}`;
  return (
    <>
      <SoftSensorConfigSummary config={state.config} t={t} />
      <SoftSensorLab key={state.selectedId} sid={state.selectedId} lab={lab} originDefault={startUtc} t={t} />
      <SoftSensorFit key={key} datasetId={datasetId} sensorId={state.selectedId} recordHours={recordHours} hasLab={lab.value !== null} labDelayS={labDelayS} t={t} onFitted={model.set} />
      {model.error !== null && <p className="status status-error" role="alert">{model.error}</p>}
      {model.loaded && <SoftSensorModel model={model.value} t={t} />}
      {model.value !== null && (
        <SoftSensorRun
          key={`${key}|${model.value.sha256}|${lab.value?.count ?? 0}`}
          datasetId={datasetId}
          sensorId={state.selectedId}
          recordHours={recordHours}
          model={model.value}
          labs={lab.value?.rows ?? []}
          labDelayS={labDelayS}
          t={t}
        />
      )}
    </>
  );
}

interface PageProps {
  datasetId: string;
  recordHours: number | null;
  /** ISO start of the dataset, offered as the origin of ISO lab sample times. */
  startUtc: string;
  t: Translate;
}

/** The Soft sensor view; `datasetId` is the dataset chosen in the app, `recordHours` its length. */
export function SoftSensorPage({ datasetId, recordHours, startUtc, t }: PageProps) {
  const state = useSoftSensors(t);
  return (
    <section>
      <header className="toolbar">
        <h2>{t("soft.title")}</h2>
        <span className="badge">{t("soft.mode.advisory")}</span>
      </header>
      <SoftSensorNotes t={t} />
      {state.error !== null && <p className="status status-error" role="alert">{t("trends.error", { reason: state.error })}</p>}
      <SensorPicker state={state} t={t} />
      <SensorBody state={state} datasetId={datasetId} recordHours={recordHours} startUtc={startUtc} t={t} />
    </section>
  );
}

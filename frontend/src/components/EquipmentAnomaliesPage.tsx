// Equipment anomaly worklist joins catalogue hierarchy with learned and live runtime state.
// Learning and operator actions refresh authoritative server state after successful writes.
import { useCallback, useEffect, useState } from "react";
import { API_PREFIX, fetchDatasets, getJson, type DatasetSummary } from "../api";
import { useCan } from "../AuthContext";
import { fetchEquipmentAnomalies, fetchEquipmentModels, learnEquipment, shelveEquipment,
  unshelveEquipment, setEquipmentOutcome, type EquipmentAnomaly, type EquipmentModelSummary,
  type EquipmentEvent, type EquipmentOutcome } from "../equipmentAnomalyApi";
import type { Translate } from "../findings";
import { ANOMALY_TABS } from "../navGroups";
import { AnomalyPage } from "./AnomalyPage";
import { EquipmentEventEvidence, EquipmentEventHistory } from "./EquipmentAnomalyEvents";
import { EquipmentLearnForm } from "./EquipmentLearnForm";
import { equipmentArea, orderedEquipment } from "./equipmentAnomalyModel";
import type { Equipment, SiteDoc } from "./equipmentModel";

const REFRESH_MS = 30_000; // Milliseconds between live worklist refreshes.
const SHELVE_MS = 3_600_000; // Milliseconds in the proposed one-hour shelving period.
const message = (problem: unknown) => problem instanceof Error ? problem.message : String(problem);

/** Load a consistent display snapshot, retaining errors rather than implying normal operation. */
function useEquipmentWorklist() {
  const [snapshot, setSnapshot] = useState<{ entries: Equipment[]; rows: EquipmentAnomaly[];
    models: EquipmentModelSummary[]; datasets: DatasetSummary[] } | null>(null);
  const [error, setError] = useState("");
  const refresh = useCallback(async () => {
    try {
      const [site, rows, models, datasets] = await Promise.all([
        getJson<SiteDoc>(`${API_PREFIX}/site`), fetchEquipmentAnomalies(), fetchEquipmentModels(), fetchDatasets(),
      ]);
      setSnapshot({ entries: site.equipment ?? [], rows, models, datasets }); setError("");
    } catch (problem) { setError(message(problem)); }
  }, []);
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);
  return { snapshot, error, refresh };
}

interface CardProps {
  entry: Equipment;
  row: EquipmentAnomaly;
  model?: EquipmentModelSummary;
  datasets: DatasetSummary[];
  datasetId: string;
  t: Translate;
  refresh: () => Promise<void>;
}

/** Route every mutation through one busy/error boundary so a failed action stays visible. */
function useEquipmentAction(refresh: () => Promise<void>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true); setError("");
    try { await action(); await refresh(); }
    catch (problem) { setError(message(problem)); }
    finally { setBusy(false); }
  };
  return { busy, error, run };
}

/** Shelving requires a future expiry; a past saved expiry does not offer an unshelve state. */
function EquipmentShelving({ row, disabled, t, run }: {
  row: EquipmentAnomaly; disabled: boolean; t: Translate;
  run: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const [until, setUntil] = useState(() => new Date(Date.now() + SHELVE_MS).toISOString().slice(0, 16));
  const isShelved = row.shelved_until_utc !== null && Date.parse(row.shelved_until_utc) > Date.now();
  if (isShelved) return <p>{t("equipmentAnomaly.shelvedUntil", { until: row.shelved_until_utc! })} <button data-testid="unshelve" disabled={disabled}
    onClick={() => void run(() => unshelveEquipment(row.equipment_id))}>{t("equipmentAnomaly.unshelve")}</button></p>;
  return <form onSubmit={(event) => { event.preventDefault(); void run(() => shelveEquipment(row.equipment_id, new Date(`${until}:00Z`).toISOString())); }}>
    <label className="field">{t("equipmentAnomaly.shelveUntil")}<input data-testid="shelve-until" type="datetime-local" required value={until} disabled={disabled}
      onChange={(event) => setUntil(event.target.value)} /></label>
    <button data-testid="shelve-submit" disabled={disabled || !until || Date.parse(`${until}:00Z`) <= Date.now()}>{t("equipmentAnomaly.shelve")}</button>
  </form>;
}

/** One equipment's model, current anomaly and operator event history. */
function EquipmentCard(props: CardProps) {
  const { entry, row, model, datasets, datasetId, t, refresh } = props;
  const canLearn = useCan("analysis.run"), canOperate = useCan("ctl.operate");
  const action = useEquipmentAction(refresh);
  const outcome = (event: EquipmentEvent, value: EquipmentOutcome) => void action.run(() => setEquipmentOutcome(event.opened_utc, entry.id, value));
  return <article className="panel" data-testid={`equipment-${entry.id}`} style={{ overflowWrap: "anywhere", minWidth: 0 }}>
    <h3>{entry.name || entry.id}</h3>
    <p>{t("equipment.criticality")}: {entry.criticality ? t(`equipmentAnomaly.criticality.${entry.criticality}`) : "—"}</p>
    <EquipmentModelPanel {...{ entry, row, model, datasets, datasetId, t }} allowed={canLearn.allowed} reason={canLearn.reason} action={action} />
    {action.error && <p role="alert">{action.error}</p>}
    <h4>{t("equipmentAnomaly.current")}</h4>
    {row.open_event ? <EquipmentEventEvidence event={row.open_event} t={t} /> : <p>{t("equipmentAnomaly.noCurrent")}</p>}
    <EquipmentShelving row={row} disabled={action.busy || !canOperate.allowed} t={t} run={action.run} />
    <h4>{t("equipmentAnomaly.history")}</h4>
    {row.events.length === 0 && <p>{t("equipmentAnomaly.noHistory")}</p>}
    {row.events.map((event) => <EquipmentEventHistory key={event.opened_utc} event={event} t={t} disabled={action.busy || !canOperate.allowed} onOutcome={outcome} />)}
  </article>;
}

/** Keep in-flight learning separate from the server's persisted model status. */
function EquipmentModelPanel({ entry, row, model, datasets, datasetId, t, allowed, reason, action }:
  Omit<CardProps, "refresh"> & { allowed: boolean; reason: string; action: ReturnType<typeof useEquipmentAction> }) {
  const [showLearn, setShowLearn] = useState(false);
  const [learning, setLearning] = useState(false);
  const learn = async (dataset: string, exclusions: [string, string][]) => {
    setLearning(true);
    try { await action.run(() => learnEquipment(dataset, entry.id, exclusions)); }
    finally { setLearning(false); }
  };
  return <>
    <p role="status">{t(`equipmentAnomaly.model.${learning ? "learning" : row.model_status}`)}</p>
    <p>{t("equipmentAnomaly.live")}: {t(`equipmentAnomaly.live.${row.live_state.shelved ? "shelved" : row.live_state.reason ? "unavailable" : row.live_state.status}`)}</p>
    <button disabled={!allowed || action.busy} title={reason} onClick={() => setShowLearn(!showLearn)}>{t("equipmentAnomaly.learn")}</button>
    {showLearn && <EquipmentLearnForm key={datasetId} datasets={datasets} datasetId={datasetId} busy={action.busy || !allowed} t={t} onLearn={learn} />}
    {model && model.windows.length > 0 && <p>{t("equipmentAnomaly.windows")}: {model.windows.map((window) => `${window[0]}–${window[1]} s`).join(", ")}</p>}
  </>;
}

/** Group catalogue equipment by area and consequence, including equipment without a model. */
function EquipmentWorklist({ datasetId, t }: { datasetId: string; t: Translate }) {
  const { snapshot, error, refresh } = useEquipmentWorklist();
  const entries = orderedEquipment(snapshot?.entries ?? []);
  const areas = [...new Set(entries.map((entry) => equipmentArea(entry, snapshot!.entries)))];
  return <section data-testid="equipment-anomalies-page">
    <h2>{t("anomaly.title")}</h2>
    <button onClick={() => void refresh()}>{t("equipmentAnomaly.refresh")}</button>
    {error && <p role="alert">{error}</p>}
    {!snapshot && !error && <p role="status">{t("trends.loading")}</p>}
    {snapshot && entries.length === 0 && <p>{t("equipmentAnomaly.empty")}</p>}
    {areas.map((area) => <section key={area} aria-label={area || t("equipmentAnomaly.noArea")}>
      <h3>{area || t("equipmentAnomaly.noArea")}</h3>
      {entries.filter((entry) => equipmentArea(entry, snapshot!.entries) === area).map((entry) => {
        const row = snapshot!.rows.find((candidate) => candidate.equipment_id === entry.id);
        return row ? <EquipmentCard key={entry.id} entry={entry} row={row} model={snapshot!.models.find((model) => model.equipment_id === entry.id)} datasets={snapshot!.datasets} datasetId={datasetId} t={t} refresh={refresh} />
          : <p key={entry.id} role="alert">{entry.name || entry.id}: {t("equipmentAnomaly.unavailable")}</p>;
      })}
    </section>)}
  </section>;
}

/** Keep the free-tag PCA detector accessible from the existing Anomalies navigation entry. */
export function EquipmentAnomaliesPage({ datasetId, recordHours, t }: { datasetId: string; recordHours: number | null; t: Translate }) {
  const [advanced, setAdvanced] = useState(false);
  return <>
    <div className="toolbar" aria-label={t("anomaly.title")}>
      {ANOMALY_TABS.map((tab) => <button key={tab} aria-pressed={advanced === (tab === "advanced")}
        onClick={() => setAdvanced(tab === "advanced")}>{t(`equipmentAnomaly.${tab}`)}</button>)}
    </div>
    {advanced ? <AnomalyPage datasetId={datasetId} recordHours={recordHours} t={t} /> : <EquipmentWorklist datasetId={datasetId} t={t} />}
  </>;
}

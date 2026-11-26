// Learn an equipment model from the chosen dataset and a proposed UTC window.
// The server still selects eligible running, automatic, unsaturated samples within that window.
import { useState, type FormEvent } from "react";
import type { DatasetSummary } from "../api";
import type { Translate } from "../findings";
import { learningExclusions } from "./equipmentAnomalyModel";

interface Props {
  datasets: DatasetSummary[];
  datasetId: string;
  busy: boolean;
  t: Translate;
  onLearn: (dataset: string, exclusions: [string, string][]) => Promise<void>;
}

/** Validate a proposed window before invoking the learning API. */
function useLearningWindow({ datasets, datasetId, t, onLearn }: Props) {
  const initial = datasets.find((dataset) => dataset.id === datasetId) ?? datasets[0];
  const [selected, setSelected] = useState(initial?.id ?? "");
  const [start, setStart] = useState(initial?.time_range.start_utc ?? "");
  const [end, setEnd] = useState(initial?.time_range.end_utc ?? "");
  const [error, setError] = useState("");
  const choose = (id: string) => {
    const dataset = datasets.find((candidate) => candidate.id === id);
    setSelected(id); setStart(dataset?.time_range.start_utc ?? ""); setEnd(dataset?.time_range.end_utc ?? "");
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError("");
    const dataset = datasets.find((candidate) => candidate.id === selected);
    if (!dataset) return;
    try { await onLearn(selected, learningExclusions(dataset, start, end)); }
    catch (problem) { setError(problem instanceof RangeError ? t("equipmentAnomaly.invalidWindow") : String(problem)); }
  };
  return { selected, start, end, error, choose, submit, setStart, setEnd };
}

/** Propose the whole record, allowing the engineer to narrow it before learning. */
export function EquipmentLearnForm(props: Props) {
  const { datasets, busy, t } = props;
  const { selected, start, end, error, choose, submit, setStart, setEnd } = useLearningWindow(props);
  return <form onSubmit={(event) => void submit(event)}>
    <p>{t("equipmentAnomaly.proposedWindow")}</p>
    <label className="field">{t("equipmentAnomaly.dataset")}<select data-testid="learn-dataset" value={selected} onChange={(event) => choose(event.target.value)} disabled={busy}>
      {datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.id}</option>)}
    </select></label>
    <label className="field">{t("equipmentAnomaly.start")}<input data-testid="learn-start" value={start} onChange={(event) => setStart(event.target.value)} required disabled={busy} /></label>
    <label className="field">{t("equipmentAnomaly.end")}<input data-testid="learn-end" value={end} onChange={(event) => setEnd(event.target.value)} required disabled={busy} /></label>
    {error && <p role="alert">{error}</p>}
    <button data-testid="learn-submit" disabled={busy || !selected}>{t(busy ? "equipmentAnomaly.learning" : "equipmentAnomaly.learn")}</button>
  </form>;
}

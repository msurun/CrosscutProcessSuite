// Fit form of the Anomalies page: a training window in hours of the record (default: the first
// N hours), checked before it is sent. A successful fit hands the new model summary to the page.
import { useState } from "react";
import { fitAnomalyModel, type AnomalyModelSummary } from "../api";
import type { Translate } from "../findings";
import { defaultTrainHours, validateWindow } from "../anomaly";
import { describeAnomalyError } from "./AnomalyState";
import { AnomalyWindowFields } from "./AnomalyWindowFields";

interface FitProps {
  datasetId: string;
  detectorId: string;
  recordHours: number | null;
  t: Translate;
  onFitted: (model: AnomalyModelSummary) => void;
}

/** The training window form and the fit button. */
export function AnomalyFit({ datasetId, detectorId, recordHours, t, onFitted }: FitProps) {
  const firstHours = defaultTrainHours(recordHours);
  const [startText, setStart] = useState("0");
  const [endText, setEnd] = useState(String(firstHours));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const check = validateWindow(startText, endText, recordHours);

  const useFirst = () => {
    setStart("0");
    setEnd(String(firstHours));
  };

  const run = (event: React.FormEvent) => {
    event.preventDefault();
    if (!check.ok || datasetId === "") return;
    setBusy(true);
    setError(null);
    fitAnomalyModel(datasetId, detectorId, { startS: check.startS, endS: check.endS })
      .then(onFitted)
      .catch((failure: unknown) => setError(describeAnomalyError(failure, t)))
      .finally(() => setBusy(false));
  };

  return (
    <section aria-label={t("anomaly.fit.title")}>
      <h3>{t("anomaly.fit.title")}</h3>
      <p className="hint">{t("anomaly.fit.hint", { dataset: datasetId })}</p>
      <form className="toolbar" onSubmit={run}>
        <AnomalyWindowFields startText={startText} endText={endText} onStart={setStart} onEnd={setEnd} check={check} recordHours={recordHours} t={t} />
        <button type="button" onClick={useFirst}>{t("anomaly.fit.useFirst", { hours: firstHours })}</button>
        <button type="submit" disabled={!check.ok || busy || datasetId === ""}>{busy ? t("anomaly.fit.running") : t("anomaly.fit.run")}</button>
      </form>
      {error !== null && <p className="status status-error" role="alert">{error}</p>}
    </section>
  );
}

// Fit form of the Soft sensor page: the train end in hours of the record (default: three quarters of
// the record), checked before it is sent. Only lab results that were AVAILABLE (sampled and reported)
// before the train end are used; the text says so. A successful fit hands the summary to the page.
import { useState } from "react";
import { fitSoftSensor, type SoftSensorModelSummary } from "../api";
import type { Translate } from "../findings";
import { defaultTrainEndHours, validateTrainEnd } from "../softsensor";
import { describeSoftError } from "./SoftSensorState";

interface FitProps {
  datasetId: string;
  sensorId: string;
  recordHours: number | null;
  hasLab: boolean;
  labDelayS: number;
  t: Translate;
  onFitted: (model: SoftSensorModelSummary) => void;
}

/** The train end field and the fit button. */
export function SoftSensorFit({ datasetId, sensorId, recordHours, hasLab, labDelayS, t, onFitted }: FitProps) {
  const defaultHours = defaultTrainEndHours(recordHours);
  const [endText, setEnd] = useState(String(defaultHours));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const check = validateTrainEnd(endText, recordHours);
  const problem = check.ok ? null : t(`soft.fit.${check.error}`, { hours: recordHours === null ? "?" : recordHours.toFixed(2) });

  const run = (event: React.FormEvent) => {
    event.preventDefault();
    if (!check.ok || datasetId === "" || !hasLab) return;
    setBusy(true);
    setError(null);
    fitSoftSensor(datasetId, sensorId, check.endS)
      .then(onFitted)
      .catch((failure: unknown) => setError(describeSoftError(failure, t)))
      .finally(() => setBusy(false));
  };

  return (
    <section aria-label={t("soft.fit.title")}>
      <h3>{t("soft.fit.title")}</h3>
      <p className="hint">{t("soft.fit.hint", { dataset: datasetId, delay: labDelayS / 60 })}</p>
      <form className="toolbar" onSubmit={run}>
        <label>
          {t("soft.fit.trainEnd")}
          <input type="text" inputMode="decimal" value={endText} onChange={(event) => setEnd(event.target.value)} aria-invalid={problem !== null} />
        </label>
        <button type="button" onClick={() => setEnd(String(defaultHours))}>{t("soft.fit.useDefault", { hours: defaultHours })}</button>
        <button type="submit" disabled={!check.ok || busy || datasetId === "" || !hasLab}>{busy ? t("soft.fit.running") : t("soft.fit.run")}</button>
      </form>
      {problem !== null && <p className="status status-error" role="alert">{problem}</p>}
      {!hasLab && <p className="status" data-testid="soft-fit-needs-lab">{t("soft.fit.needLab")}</p>}
      {error !== null && <p className="status status-error" role="alert">{error}</p>}
    </section>
  );
}

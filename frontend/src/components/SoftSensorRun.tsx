// Run form and result of the Soft sensor page: a window in hours (default: the whole record), the
// estimate chart with the flags rule, the validity counts, the summary numbers and the bias chart
// with the drift episodes. Estimates are advisory; nothing is written anywhere.
import { useState } from "react";
import { runSoftSensor, type LabRow, type SoftSensorModelSummary, type SoftSensorRun as RunResult } from "../api";
import type { Translate } from "../findings";
import { validateWindow } from "../anomaly";
import { scoreAgainstLabs } from "../softsensorSeries";
import { BiasChart, EstimateChart } from "./SoftSensorCharts";
import { SoftSensorDrift, SoftSensorScores } from "./SoftSensorScores";
import { SoftSensorValidityView } from "./SoftSensorValidity";
import { AnomalyWindowFields } from "./AnomalyWindowFields";
import { describeSoftError } from "./SoftSensorState";

const HOUR_DECIMAL_SCALE = 100;

interface RunProps {
  datasetId: string;
  sensorId: string;
  recordHours: number | null;
  model: SoftSensorModelSummary;
  labs: readonly LabRow[];
  labDelayS: number;
  t: Translate;
}

interface ResultProps {
  result: RunResult;
  model: SoftSensorModelSummary;
  labs: readonly LabRow[];
  labDelayS: number;
  t: Translate;
}

/** Everything that depends on a finished run. */
function RunResultView({ result, model, labs, labDelayS, t }: ResultProps) {
  const all = scoreAgainstLabs(result.series, labs, labDelayS, 0);
  const afterCut = scoreAgainstLabs(result.series, labs, labDelayS, model.window.end_s);
  return (
    <div data-testid="soft-result">
      <EstimateChart series={result.series} labs={labs} labDelayS={labDelayS} t={t} />
      <SoftSensorValidityView counts={result.validity_counts} t={t} />
      <SoftSensorScores all={all} afterCut={afterCut} nLabUsed={result.n_lab_used} t={t} />
      <BiasChart series={result.series} cvSigma={model.cv_sigma} t={t} />
      <SoftSensorDrift episodes={result.drift_episodes} model={model} t={t} />
    </div>
  );
}

/** The run window form, its error and the result. */
export function SoftSensorRun({ datasetId, sensorId, recordHours, model, labs, labDelayS, t }: RunProps) {
  const wholeRecord = recordHours === null ? "" : String(Math.ceil(recordHours * HOUR_DECIMAL_SCALE) / HOUR_DECIMAL_SCALE);
  const [startText, setStart] = useState("0");
  const [endText, setEnd] = useState(wholeRecord);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RunResult | null>(null);
  const check = validateWindow(startText, endText, recordHours);

  const run = (event: React.FormEvent) => {
    event.preventDefault();
    if (!check.ok || datasetId === "") return;
    setBusy(true);
    setError(null);
    runSoftSensor(datasetId, sensorId, { startS: check.startS, endS: check.endS })
      .then(setResult)
      .catch((failure: unknown) => setError(describeSoftError(failure, t)))
      .finally(() => setBusy(false));
  };

  return (
    <section aria-label={t("soft.run.title")}>
      <h3>{t("soft.run.title")}</h3>
      <p className="hint">{t("soft.run.hint")}</p>
      <form className="toolbar" onSubmit={run}>
        <AnomalyWindowFields startText={startText} endText={endText} onStart={setStart} onEnd={setEnd} check={check} recordHours={recordHours} t={t} />
        <button type="submit" disabled={!check.ok || busy || datasetId === ""}>{busy ? t("soft.run.running") : t("soft.run.run")}</button>
      </form>
      {error !== null && <p className="status status-error" role="alert">{error}</p>}
      {result !== null && <RunResultView result={result} model={model} labs={labs} labDelayS={labDelayS} t={t} />}
    </section>
  );
}

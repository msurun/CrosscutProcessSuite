// Scan form and result of the Anomalies page: a window in hours (default: the whole record), the
// T2 and SPE charts, the events table, the contribution bars of the selected event and the line
// that says how many rows were not used (they are never imputed).
import { useState } from "react";
import { scanAnomalies, type AnomalyScan as ScanResult } from "../api";
import type { Translate } from "../findings";
import { validateWindow } from "../anomaly";
import { AnomalyCharts } from "./AnomalyCharts";
import { AnomalyContributions } from "./AnomalyContributions";
import { AnomalyEventsTable } from "./AnomalyEvents";
import { describeAnomalyError } from "./AnomalyState";
import { AnomalyWindowFields } from "./AnomalyWindowFields";

const HOUR_DECIMAL_SCALE = 100;

interface ScanProps {
  datasetId: string;
  detectorId: string;
  recordHours: number | null;
  t: Translate;
}

/** Everything that depends on a finished scan. */
function ScanResultView({ result, t }: { result: ScanResult; t: Translate }) {
  const [selected, setSelected] = useState(0);
  const event = result.events[Math.min(selected, result.events.length - 1)];
  const skipped = result.skipped_reasons;
  return (
    <div data-testid="anomaly-result">
      <p className="status" role="status">{t("anomaly.rows", { nan: skipped.nan ?? 0, quality: skipped.quality ?? 0, valid: result.n_valid })}</p>
      <AnomalyCharts series={result.series} events={result.events} t={t} />
      <h3>{t("anomaly.events.title")}</h3>
      <AnomalyEventsTable events={result.events} t2Limit={result.series.t2_limit} speLimit={result.series.spe_limit} selected={selected} onSelect={setSelected} t={t} />
      {event !== undefined && <AnomalyContributions event={event} number={result.events.indexOf(event) + 1} t={t} />}
    </div>
  );
}

/** The scan window form, its error and the result. */
export function AnomalyScan({ datasetId, detectorId, recordHours, t }: ScanProps) {
  const wholeRecord = recordHours === null ? "" : String(Math.ceil(recordHours * HOUR_DECIMAL_SCALE) / HOUR_DECIMAL_SCALE);
  const [startText, setStart] = useState("0");
  const [endText, setEnd] = useState(wholeRecord);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ScanResult | null>(null);
  const check = validateWindow(startText, endText, recordHours);

  const run = (event: React.FormEvent) => {
    event.preventDefault();
    if (!check.ok || datasetId === "") return;
    setBusy(true);
    setError(null);
    scanAnomalies(datasetId, detectorId, { startS: check.startS, endS: check.endS })
      .then(setResult)
      .catch((failure: unknown) => setError(describeAnomalyError(failure, t)))
      .finally(() => setBusy(false));
  };

  return (
    <section aria-label={t("anomaly.scan.title")}>
      <h3>{t("anomaly.scan.title")}</h3>
      <p className="hint">{t("anomaly.scan.hint")}</p>
      <form className="toolbar" onSubmit={run}>
        <AnomalyWindowFields startText={startText} endText={endText} onStart={setStart} onEnd={setEnd} check={check} recordHours={recordHours} t={t} />
        <button type="submit" disabled={!check.ok || busy || datasetId === ""}>{busy ? t("anomaly.scan.running") : t("anomaly.scan.run")}</button>
      </form>
      {error !== null && <p className="status status-error" role="alert">{error}</p>}
      {result !== null && <ScanResultView result={result} t={t} />}
    </section>
  );
}

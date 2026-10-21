// "Advise now" and the replay form of the Advisory page, with their result lists. Advice shown
// here is not decided on: decisions are recorded in the log view, only for advice that is in the log.
import { useState } from "react";
import { adviseNow, replaySupervisor, type AdviceRecord, type AdviseNowResult, type SupervisorReplayResult } from "../api";
import type { Translate } from "../findings";
import { gateChipClass } from "../advisory";
import { AdviceCard } from "./AdviceCard";
import { describeError } from "./AdvisoryState";

/** How many replay advices are drawn; the count of all is always shown. */
const MAX_SHOWN = 30;
const DEFAULT_WINDOW_S = 1800;
const DEFAULT_STEP_S = 300;

interface RunProps {
  datasetId: string;
  supervisorId: string;
  t: Translate;
  /** Called after a replay that wrote to the log, so the log view reloads. */
  onRecorded: () => void;
}

/** "Advise now": one advice on the end of the chosen dataset; the log is not written. */
function AdviseNow({ datasetId, supervisorId, t }: Omit<RunProps, "onRecorded">) {
  const [result, setResult] = useState<AdviseNowResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const run = () => {
    setError(null);
    adviseNow(datasetId, supervisorId).then(setResult).catch((failure: unknown) => setError(describeError(failure)));
  };
  return (
    <section aria-label={t("advisory.now.title")}>
      <h3>{t("advisory.now.title")}</h3>
      <p className="hint">{t("advisory.now.hint", { dataset: datasetId })}</p>
      <button type="button" className="filter-chip" onClick={run} disabled={datasetId === ""}>{t("advisory.now.run")}</button>
      {error !== null && <p className="status status-error" role="alert">{t("trends.error", { reason: error })}</p>}
      {result !== null && result.advice !== null && <ul className="advice-list"><AdviceCard advice={result.advice} t={t} /></ul>}
      {result !== null && result.advice === null && (
        <p className="status">
          {t("advisory.now.none")}{" "}
          <span className={gateChipClass(result.gate.state)}>{t("advisory.gate", { state: t(`advisory.gate.${result.gate.state}`) })}</span>
          {result.gate.reasons.length > 0 && ` ${t("advisory.gate.reasons", { reasons: result.gate.reasons.join(", ") })}`}
        </p>
      )}
    </section>
  );
}

/** The advices a replay returned, capped at MAX_SHOWN. */
function ReplayResult({ result, t }: { result: SupervisorReplayResult; t: Translate }) {
  const shown: AdviceRecord[] = result.advices.slice(0, MAX_SHOWN);
  return (
    <>
      <p className="status" role="status">
        {t("advisory.replay.summary", { count: result.advices.length, recorded: result.recorded })}
        {result.advices.length > shown.length && ` ${t("advisory.replay.capped", { shown: shown.length })}`}
      </p>
      <ul className="advice-list">
        {shown.map((advice) => <AdviceCard key={advice.advice_id} advice={advice} t={t} />)}
      </ul>
    </>
  );
}

/** The replay form: window and step in seconds, and "record to log" (default off). */
function Replay({ datasetId, supervisorId, t, onRecorded }: RunProps) {
  const [windowS, setWindowS] = useState(String(DEFAULT_WINDOW_S));
  const [stepS, setStepS] = useState(String(DEFAULT_STEP_S));
  const [record, setRecord] = useState(false);
  const [result, setResult] = useState<SupervisorReplayResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const valid = Number(windowS) > 0 && Number(stepS) > 0;

  const run = (event: React.FormEvent) => {
    event.preventDefault();
    if (!valid) return;
    setError(null);
    replaySupervisor(datasetId, supervisorId, { windowS: Number(windowS), stepS: Number(stepS), record })
      .then((replayed) => {
        setResult(replayed);
        if (replayed.recorded > 0) onRecorded();
      })
      .catch((failure: unknown) => setError(describeError(failure)));
  };

  return (
    <section aria-label={t("advisory.replay.title")}>
      <h3>{t("advisory.replay.title")}</h3>
      <p className="hint">{t("advisory.replay.hint")}</p>
      <form className="toolbar" onSubmit={run}>
        <label>{t("advisory.replay.window")} <input type="number" min="1" value={windowS} onChange={(event) => setWindowS(event.target.value)} /></label>
        <label>{t("advisory.replay.step")} <input type="number" min="1" value={stepS} onChange={(event) => setStepS(event.target.value)} /></label>
        <label><input type="checkbox" checked={record} onChange={(event) => setRecord(event.target.checked)} /> {t("advisory.replay.record")}</label>
        <button type="submit" className="filter-chip" disabled={datasetId === "" || !valid}>{t("advisory.replay.run")}</button>
      </form>
      {error !== null && <p className="status status-error" role="alert">{t("trends.error", { reason: error })}</p>}
      {result !== null && <ReplayResult result={result} t={t} />}
    </section>
  );
}

/** Both run controls of the page. */
export function AdvisoryRun(props: RunProps) {
  return (
    <>
      <AdviseNow datasetId={props.datasetId} supervisorId={props.supervisorId} t={props.t} />
      <Replay {...props} />
    </>
  );
}

// Steps view: analyze the steps of one loop of a dataset, show a table of fits with their
// uncertainties and verdicts, and a chart of the selected step's samples.
// Calls the backend one loop at a time (see docs/design/step-analyzer.md); nothing reaches a plant.
import { useEffect, useRef, useState } from "react";
import { fetchTags } from "../api";
import type { Translate } from "../findings";
import { analyzeSteps, logbookFromCsv, parseLogbook } from "../stepAnalyzer";
import type { StepsPayload, StepRow, StepsRequest, StepSummary } from "../stepAnalyzer";
import { StepDetail, StepsTable } from "./StepsTable";
import { TargetFields, sortedTagNames } from "./StepsTarget";
import type { TargetChoice, TargetFieldsProps } from "./StepsTarget";

/** Offset of the plant local time east of UTC used when parsing the logbook by default. */
const DEFAULT_OFFSET_HOURS = "-3";

/** Model choices of the model select; "auto" lets the server pick FOPDT or IPDT by BIC. */
const MODEL_CHOICES = ["auto", "fopdt", "ipdt"] as const;
type ModelChoice = (typeof MODEL_CHOICES)[number];

/** Parameters shown per summary line, with the number of decimals used for the median. */
const SUMMARY_DIGITS = 2;

interface PageProps {
  datasetId: string;
  /** Loops of the dataset, used for the loop select. */
  loopNames: string[];
  /** Loop selected when the view opens; falls back to the first loop. */
  initialLoop: string | null;
  t: Translate;
}

/** Read the CSV chosen in a logbook file input and hand its lines to `onLogbook`. */
async function loadLogbookFile(input: HTMLInputElement, onLogbook: (text: string) => void) {
  const file = input.files?.[0];
  input.value = "";
  if (file === undefined) return;
  onLogbook(logbookFromCsv(await file.text()));
}

/** The target choice, the model select, the logbook textarea with its offset input and Run. */
function StepsForm({ target, model, logbookText, offsetHours, busy, canRun, onRun, onModel, onLogbook, onOffset, t }: {
  target: TargetFieldsProps;
  model: ModelChoice;
  logbookText: string;
  offsetHours: string;
  busy: boolean;
  canRun: boolean;
  onRun: () => void;
  onModel: (model: ModelChoice) => void;
  onLogbook: (text: string) => void;
  onOffset: (hours: string) => void;
  t: Translate;
}) {
  return (
    <div className="knowledge-fields">
      <TargetFields {...target} />
      <div className="field">
        <label className="field-label" htmlFor="steps-model">{t("steps.model")}</label>
        <select id="steps-model" className="field-input" value={model}
          onChange={(event) => onModel(event.target.value as ModelChoice)}>
          {MODEL_CHOICES.map((choice) => (
            <option key={choice} value={choice}>{t(`steps.model.${choice}`)}</option>
          ))}
        </select>
      </div>
      <div className="field">
        <label className="field-label" htmlFor="steps-logbook">{t("steps.logbook.label")}</label>
        <textarea id="steps-logbook" className="field-input" rows={4} value={logbookText}
          aria-describedby="steps-logbook-hint"
          onChange={(event) => onLogbook(event.target.value)} />
        <span id="steps-logbook-hint" className="field-help hint">{t("steps.logbook.hint")}</span>
        <label className="field-label" htmlFor="steps-logbook-file">{t("steps.logbook.load")}</label>
        <input id="steps-logbook-file" className="field-input" type="file" accept=".csv,text/csv"
          aria-describedby="steps-logbook-hint"
          onChange={(event) => void loadLogbookFile(event.target, onLogbook)} />
      </div>
      <div className="field">
        <label className="field-label" htmlFor="steps-offset">{t("steps.logbook.offset")}</label>
        <input id="steps-offset" className="field-input" type="text" inputMode="decimal"
          value={offsetHours} onChange={(event) => onOffset(event.target.value)} />
      </div>
      <div className="toolbar">
        <button type="button" disabled={busy || !canRun} onClick={onRun}>
          {busy ? t("steps.running") : t("steps.run")}
        </button>
      </div>
    </div>
  );
}

/** Format an optional median parameter with `SUMMARY_DIGITS` decimals; "–" when absent. */
function medianText(value: number | null | undefined): string {
  if (value === null || value === undefined) return "\u2013";
  return value.toFixed(SUMMARY_DIGITS);
}

/** One summary line per model: median key parameter, tau, theta and the count of consistent rows. */
function summaryLine(summary: StepSummary, t: Translate): string {
  const isIntegrating = summary.model === "ipdt";
  const gain = isIntegrating ? medianText(summary.median_slope) : medianText(summary.median_gain);
  return t("steps.summary.line", {
    model: t(`steps.model.${summary.model}`),
    gain,
    tau: medianText(summary.median_tau_s),
    theta: medianText(summary.median_theta_s),
    ok: summary.n_consistent,
    total: summary.n_rows,
  });
}

/** The per-model summary list and the count of events dropped before fitting. */
function StepsSummary({ payload, t }: { payload: StepsPayload; t: Translate }) {
  const summaries = payload.summary ?? [];
  return (
    <section aria-label={t("steps.summary.title")}>
      <h3>{t("steps.summary.title")}</h3>
      {summaries.map((summary) => (
        <p key={summary.model} className="status" role="status">{summaryLine(summary, t)}</p>
      ))}
      {payload.skipped.length > 0 && (
        <p className="status status-warning" role="status">
          {t("steps.skipped", { count: payload.skipped.length })}
        </p>
      )}
    </section>
  );
}

/** The step table and, once a row is picked, the chart of that step's window. */
function StepsResults({ payload, selectedId, onSelect, t }: {
  payload: StepsPayload;
  selectedId: string | null;
  onSelect: (id: string) => void;
  t: Translate;
}) {
  const selected = findRow(payload.rows, selectedId);
  if (payload.rows.length === 0) return <p className="status" role="status">{t("steps.empty")}</p>;
  return (
    <>
      <StepsTable rows={payload.rows} selectedId={selectedId} onSelect={onSelect} t={t} />
      {selected !== null && <StepDetail row={selected} t={t} />}
    </>
  );
}

/** Return the row with `id`, or the first row when nothing (or a stale id) is selected. */
function findRow(rows: StepRow[], id: string | null): StepRow | null {
  if (rows.length === 0) return null;
  return rows.find((row) => row.id === id) ?? rows[0];
}

/** Target part of the request: the tag pair in tags mode, the loop otherwise. */
function targetBody(choice: TargetChoice, loop: string, driver: string, output: string): StepsRequest {
  return choice === "tags" ? { driver, output } : { loop };
}

/** The steps section: choose loop and model, paste the logbook, then analyze and inspect steps. */
export function StepsPage({ datasetId, loopNames, initialLoop, t }: PageProps) {
  const [choice, setChoice] = useState<TargetChoice>("loop");
  const [loop, setLoop] = useState(initialLoop ?? loopNames[0] ?? "");
  const [driver, setDriver] = useState("");
  const [output, setOutput] = useState("");
  const [tagNames, setTagNames] = useState<string[]>([]);
  const [model, setModel] = useState<ModelChoice>("auto");
  const [logbookText, setLogbookText] = useState("");
  const [offsetHours, setOffsetHours] = useState(DEFAULT_OFFSET_HOURS);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [payload, setPayload] = useState<StepsPayload | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const latestRequest = useRef(0);

  useEffect(() => {
    let ignore = false;
    setDriver("");
    setOutput("");
    fetchTags(datasetId)
      .then((tags) => { if (!ignore) setTagNames(sortedTagNames(tags)); })
      .catch(() => { if (!ignore) setTagNames([]); });
    return () => { ignore = true; };
  }, [datasetId]);

  const canRun = choice === "tags" ? driver !== "" && output !== "" : loopNames.length > 0;
  const target: TargetFieldsProps = {
    choice, onChoice: setChoice, loop, loopNames, onLoop: setLoop,
    tagNames, driver, output, onDriver: setDriver, onOutput: setOutput, t,
  };

  async function runAnalysis() {
    const requestNumber = latestRequest.current + 1;
    latestRequest.current = requestNumber;
    setBusy(true);
    setError(null);
    try {
      const entries = parseLogbook(logbookText, Number(offsetHours));
      const result = await analyzeSteps(datasetId, {
        ...targetBody(choice, loop, driver, output), model, logbook: entries,
      });
      if (requestNumber !== latestRequest.current) return;
      setPayload(result);
      setSelectedId(result.rows[0]?.id ?? null);
    } catch (failure) {
      if (requestNumber === latestRequest.current) setError(errorText(failure));
    } finally {
      if (requestNumber === latestRequest.current) setBusy(false);
    }
  }

  return (
    <section>
      <header className="toolbar"><h2>{t("steps.title")}</h2></header>
      <p className="notice banner-warning" role="note">{t("steps.note")}</p>
      <StepsForm target={target} model={model} logbookText={logbookText}
        offsetHours={offsetHours} busy={busy} canRun={canRun} onRun={runAnalysis}
        onModel={setModel} onLogbook={setLogbookText} onOffset={setOffsetHours} t={t} />
      {error !== null && <p className="status status-error" role="alert">{error}</p>}
      {payload !== null && (
        <>
          <StepsSummary payload={payload} t={t} />
          <StepsResults payload={payload} selectedId={selectedId} onSelect={setSelectedId} t={t} />
        </>
      )}
    </section>
  );
}

/** Turn a thrown value into the text shown in the alert. */
function errorText(failure: unknown): string {
  return failure instanceof Error ? failure.message : String(failure);
}

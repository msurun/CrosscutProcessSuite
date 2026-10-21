/**
 * "Backtest" tab: scores what a rule base advises just before each operator setpoint move.
 * Illustrative only: a banner says so, and nothing is written to the plant.
 */

import { variableLabel } from "../fuzzyNames";
import { useState } from "react";
import { backtestFuzzy, type BacktestMetrics, type FuzzyBacktest } from "../api";
import type { Translate } from "../findings";
import type { FuzzyDocument } from "../fuzzy";

/** Defaults of the three settings; they mirror BacktestSettings in the fuzzy package. */
const DEFAULT_DEAD_BAND = "2";
const DEFAULT_LOOKBACK_S = "900";
const DEFAULT_SILENT_BAND = "1";

const NO_VALUE = "\u2014";

interface SettingsText {
  deadBand: string;
  lookbackS: string;
  silentBand: string;
}

const DEFAULT_SETTINGS: SettingsText = {
  deadBand: DEFAULT_DEAD_BAND,
  lookbackS: DEFAULT_LOOKBACK_S,
  silentBand: DEFAULT_SILENT_BAND,
};

/** True when `text` is a finite number that is not negative. */
function isValidNumber(text: string): boolean {
  const value = Number(text);
  return text.trim() !== "" && Number.isFinite(value) && value >= 0;
}

/** True when all three settings can be sent. */
function areSettingsValid(settings: SettingsText): boolean {
  return [settings.deadBand, settings.lookbackS, settings.silentBand].every(isValidNumber);
}

/** A share (0..1) as a percentage, or a dash when it could not be measured. */
function formatShare(value: number | null): string {
  return value === null ? NO_VALUE : `${Math.round(value * 100)}%`;
}

/** A correlation with two decimals, or a dash. */
function formatCorrelation(value: number | null): string {
  return value === null ? NO_VALUE : value.toFixed(2);
}

/** The persistent "illustrative, not validated" warning. */
function IllustrativeBanner({ t }: { t: Translate }) {
  return (
    <p role="note" className="banner banner-warning">
      {t("fuzzy.backtest.banner")}
    </p>
  );
}

interface SettingsFormProps {
  document: FuzzyDocument;
  outputId: string;
  settings: SettingsText;
  onOutput: (outputId: string) => void;
  onSettings: (settings: SettingsText) => void;
  t: Translate;
}

/** Output selector and the three scoring settings. */
function SettingsForm({ document, outputId, settings, onOutput, onSettings, t }: SettingsFormProps) {
  const numberField = (key: keyof SettingsText, label: string) => (
    <label>
      {label}
      <input
        type="number"
        min={0}
        step="any"
        value={settings[key]}
        aria-invalid={!isValidNumber(settings[key])}
        onChange={(event) => onSettings({ ...settings, [key]: event.target.value })}
      />
    </label>
  );
  return (
    <div className="toolbar">
      <label>
        {t("fuzzy.backtest.output")}
        <select value={outputId} onChange={(event) => onOutput(event.target.value)}>
          {document.outputs.map((output) => (
            <option key={output.id} value={output.id}>
              {variableLabel(t, output)}
            </option>
          ))}
        </select>
      </label>
      {numberField("deadBand", t("fuzzy.backtest.deadBand"))}
      {numberField("lookbackS", t("fuzzy.backtest.lookback"))}
      {numberField("silentBand", t("fuzzy.backtest.silentBand"))}
    </div>
  );
}

/** One table row: a part of the recording and its metrics. */
function MetricsRow({ label, metrics }: { label: string; metrics: BacktestMetrics }) {
  return (
    <tr>
      <th scope="row">{label}</th>
      <td>{metrics.n_moves}</td>
      <td>{formatShare(metrics.sign_agreement)}</td>
      <td>{formatCorrelation(metrics.correlation)}</td>
      <td>{formatShare(metrics.majority_share)}</td>
      <td>{formatShare(metrics.silent_share)}</td>
    </tr>
  );
}

/** Summary table of the whole record and its two halves. */
function ResultTable({ result, t }: { result: FuzzyBacktest; t: Translate }) {
  return (
    <table className="settings-table">
      <caption>{t("fuzzy.backtest.results", { name: result.output })}</caption>
      <thead>
        <tr>
          <th scope="col">{t("fuzzy.backtest.part")}</th>
          <th scope="col">{t("fuzzy.backtest.moves")}</th>
          <th scope="col">{t("fuzzy.backtest.signAgreement")}</th>
          <th scope="col">{t("fuzzy.backtest.correlation")}</th>
          <th scope="col">{t("fuzzy.backtest.majority")}</th>
          <th scope="col">{t("fuzzy.backtest.silent")}</th>
        </tr>
      </thead>
      <tbody>
        <MetricsRow label={t("fuzzy.backtest.all")} metrics={result.all} />
        <MetricsRow label={t("fuzzy.backtest.firstHalf")} metrics={result.first_half} />
        <MetricsRow label={t("fuzzy.backtest.secondHalf")} metrics={result.second_half} />
      </tbody>
    </table>
  );
}

interface RunState {
  isRunning: boolean;
  result: FuzzyBacktest | null;
  error: string | null;
}

const IDLE: RunState = { isRunning: false, result: null, error: null };

/** Panel that backtests `document` on `datasetId`; the banner is always visible. */
export function BacktestPanel({ datasetId, document, t }: { datasetId: string; document: FuzzyDocument; t: Translate }) {
  const [outputId, setOutputId] = useState(document.outputs[0]?.id ?? "");
  const [settings, setSettings] = useState<SettingsText>(DEFAULT_SETTINGS);
  const [run, setRun] = useState<RunState>(IDLE);

  async function handleRun(): Promise<void> {
    setRun({ isRunning: true, result: null, error: null });
    try {
      const result = await backtestFuzzy(datasetId, document, outputId, {
        deadBand: Number(settings.deadBand),
        lookbackS: Number(settings.lookbackS),
        silentBand: Number(settings.silentBand),
      });
      setRun({ isRunning: false, result, error: null });
    } catch (failure) {
      const reason = failure instanceof Error ? failure.message : String(failure);
      setRun({ isRunning: false, result: null, error: reason });
    }
  }

  const canRun = datasetId !== "" && outputId !== "" && areSettingsValid(settings) && !run.isRunning;
  return (
    <>
      <h3>{t("fuzzy.backtest")}</h3>
      <IllustrativeBanner t={t} />
      <p className="hint">{t("fuzzy.backtest.hint")}</p>
      <SettingsForm document={document} outputId={outputId} settings={settings} onOutput={setOutputId} onSettings={setSettings} t={t} />
      <button type="button" className="filter-chip" disabled={!canRun} onClick={() => void handleRun()}>
        {t("fuzzy.backtest.run")}
      </button>
      {datasetId === "" && <p className="status">{t("fuzzy.dataset.none")}</p>}
      {run.isRunning && <p className="status">{t("trends.loading")}</p>}
      {run.error !== null && <p className="status status-error">{t("trends.error", { reason: run.error })}</p>}
      {run.result !== null && <ResultTable result={run.result} t={t} />}
    </>
  );
}

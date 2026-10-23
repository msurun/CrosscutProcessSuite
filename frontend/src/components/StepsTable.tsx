// Table of the detected steps of one loop, plus the detail of the selected step.
// Used by the Steps view (docs/design/step-analyzer.md): every row is a fitted step with its
// verdict; clicking the first cell selects it and shows PV/fit/OUT of its window below.
import { paramText, verdictClass, type StepParam, type StepRow } from "../stepAnalyzer";
import type { Translate } from "../findings";
import { TrendPane } from "./TrendPane";

const PANE_HEIGHT_PX = 150;

/** Seconds in one minute, used to plot the window on a minutes axis. */
const SECONDS_PER_MINUTE = 60;

/** Sample points above this count are thinned so the chart stays readable. */
const MAX_CHART_POINTS = 300;

/** Columns of the table, in display order; the gain/slope pair depends on the model. */
const COLUMN_KEYS = [
  "time", "kind", "size", "snr", "model", "gain", "slope",
  "tau", "theta", "r2", "verdict", "test", "logbook",
] as const;

type ColumnKey = (typeof COLUMN_KEYS)[number];

/** Text of one verdict reason: translated when known, the raw code otherwise. */
function reasonText(code: string, t: Translate): string {
  const key = `steps.reason.${code}`;
  const text = t(key);
  return text === key ? code : text;
}

/** One parameter cell: "value ± se" with the design's two decimals, or an en dash. */
function ParamCell({ param }: { param: StepParam | undefined }) {
  return <td className="num">{paramText(param)}</td>;
}

/** Verdict chip with the verdict text and its reasons. */
function VerdictCell({ row, t }: { row: StepRow; t: Translate }) {
  const reasons = row.reasons.map((code) => reasonText(code, t)).join(", ");
  return (
    <td>
      <span className={`chip chip-${verdictClass(row.verdict)}`}>{t(`steps.verdict.${row.verdict}`)}</span>
      {reasons !== "" && <span className="reason-text"> {reasons}</span>}
    </td>
  );
}

/** Value of one plain cell; gain and slope share the parameter rendering. */
function cellValue(key: ColumnKey, row: StepRow, t: Translate) {
  if (key === "time") return row.event_utc;
  if (key === "kind") return t(`steps.kind.${row.kind}`);
  if (key === "size") return row.size.toFixed(2);
  if (key === "snr") return row.snr === null ? "\u2013" : row.snr.toFixed(1);
  if (key === "model") return row.model === null ? "\u2013" : row.model.toUpperCase();
  if (key === "r2") return row.r2 === null ? "\u2013" : row.r2.toFixed(2);
  if (key === "test") return row.test_label ?? "\u2013";
  if (key === "logbook") return row.logbook.map((entry) => entry.text).join("; ") || "\u2013";
  return null;
}

/** First cell: a real button so clicking and keyboard selection both work. */
function SelectCell({ row, selectedId, onSelect }: {
  row: StepRow;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <td>
      <button
        type="button"
        className="link-button"
        aria-pressed={row.id === selectedId}
        onClick={() => onSelect(row.id)}
      >
        {row.event_utc}
      </button>
    </td>
  );
}

/** Parameter cells for gain and slope, absent values shown as an en dash. */
function GainCells({ row }: { row: StepRow }) {
  return (
    <>
      <ParamCell param={row.params.gain} />
      <ParamCell param={row.params.slope} />
    </>
  );
}

/** Parameter cells for tau and theta. */
function TimeCells({ row }: { row: StepRow }) {
  return (
    <>
      <ParamCell param={row.params.tau_s} />
      <ParamCell param={row.params.theta_s} />
    </>
  );
}

/** One table row: selection button, plain cells, parameters and verdict chip. */
function StepTableRow({ row, selectedId, onSelect, t }: {
  row: StepRow;
  selectedId: string | null;
  onSelect: (id: string) => void;
  t: Translate;
}) {
  return (
    <tr>
      <SelectCell row={row} selectedId={selectedId} onSelect={onSelect} />
      <td>{cellValue("kind", row, t)}</td>
      <td className="num">{cellValue("size", row, t)}</td>
      <td className="num">{cellValue("snr", row, t)}</td>
      <td>{cellValue("model", row, t)}</td>
      <GainCells row={row} />
      <TimeCells row={row} />
      <td className="num">{cellValue("r2", row, t)}</td>
      <VerdictCell row={row} t={t} />
      <td>{cellValue("test", row, t)}</td>
      <td>{cellValue("logbook", row, t)}</td>
    </tr>
  );
}

/**
 * Table of the steps: one row per detected event of the loop.
 * The first column holds a button that selects the row (aria-pressed when selected).
 */
export function StepsTable({ rows, selectedId, onSelect, t }: {
  rows: StepRow[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  t: Translate;
}) {
  const label = t("steps.title");
  return (
    <div className="table-scroll" tabIndex={0} role="region" aria-label={label}>
      <table className="steps-table">
        <caption>{label}</caption>
        <thead>
          <tr>{COLUMN_KEYS.map((key) => <th key={key} scope="col">{t(`steps.col.${key}`)}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <StepTableRow key={row.id} row={row} selectedId={selectedId} onSelect={onSelect} t={t} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Keep at most `MAX_CHART_POINTS` evenly spaced indices of a series. */
function thinIndices(length: number): number[] {
  if (length <= MAX_CHART_POINTS) return Array.from({ length }, (_, i) => i);
  const step = length / MAX_CHART_POINTS;
  return Array.from({ length: MAX_CHART_POINTS }, (_, i) => Math.floor(i * step));
}

/** Window samples in minutes from the window start, thinned for the chart. */
function chartSeries(row: StepRow) {
  const indices = thinIndices(row.sample.t_s.length);
  const minutes = indices.map((i) => row.sample.t_s[i] / SECONDS_PER_MINUTE);
  const pv = indices.map((i) => row.sample.pv[i]);
  const out = indices.map((i) => row.sample.out[i]);
  const fit = indices.map((i) => row.sample.fit[i] ?? Number.NaN);
  return { minutes, pv, out, fit };
}

/** PV and fitted model in one pane, OUT in another; nothing when the sample is empty. */
function StepChart({ row, t }: { row: StepRow; t: Translate }) {
  const { minutes, pv, out, fit } = chartSeries(row);
  if (minutes.length === 0) return null;
  const pvLabel = t("steps.chart.pv");
  const fitLabel = t("steps.chart.fit");
  const outLabel = t("steps.chart.out");
  const common = { height: PANE_HEIGHT_PX, syncKey: "steps", xIsTime: false, xLabel: t("steps.chart.axis"), t } as const;
  return (
    <div data-testid="step-chart">
      <figure className="anomaly-chart">
        <figcaption>{t("steps.chart.title")}</figcaption>
        <TrendPane
          data={[minutes, pv, fit]}
          labels={[pvLabel, fitLabel]}
          colors={["--series-1", "--series-3"]}
          roles={["pv", "sp"]}
          {...common}
        />
      </figure>
      <figure className="anomaly-chart">
        <figcaption>{outLabel}</figcaption>
        <TrendPane data={[minutes, out]} labels={[outLabel]} colors={["--series-2"]} roles={["out"]} {...common} />
      </figure>
    </div>
  );
}

/** The model chosen when `model` is "auto", with its BIC, or null when none was tried. */
function AltModelLine({ row, t }: { row: StepRow; t: Translate }) {
  if (row.alt_model === null) return null;
  const { model, bic } = row.alt_model;
  return <p className="notice">{t("steps.alt_model", { model: model.toUpperCase(), bic: bic.toFixed(1) })}</p>;
}

/** Detail of the selected step: its chart, the alternative model and the optional note. */
export function StepDetail({ row, t }: { row: StepRow; t: Translate }) {
  return (
    <section aria-label={t("steps.chart.title")}>
      <h3>{row.event_utc}</h3>
      <StepChart row={row} t={t} />
      <AltModelLine row={row} t={t} />
      {row.detail !== undefined && <p className="notice">{row.detail}</p>}
    </section>
  );
}

// src/components/ValveResultView.tsx
//
// Shows the analysis of a recorded valve stroke test: a plain-language verdict
// first, then the numbers, the charts and the list of detected steps.

import type { ValveAnalysis, ValveResult } from "../api";
import type { LoopSummary } from "../api";
import type { Translate } from "../findings";
import { formatSignificant } from "../format";
import { TrendPane } from "./TrendPane";

/** Deadband below this share of span (% of span) is not worth flagging to the user. */
const DEADBAND_GOOD_PERCENT = 0.1;

/** Height of each trend pane in pixels. */
const CHART_HEIGHT = 160;

/** Shared x-axis group of the two panes, so zooming one zooms the other. */
const CHART_SYNC_KEY = "valve-result";

/** Colour of the controller output series (kept in step with the rest of the UI). */
const OP_COLOR = "--series-3";

/** Colour of the process value series. */
const PV_COLOR = "--series-1";

/** Unit of the controller output, always a percentage. */
const OP_UNIT = "%";

/** Placeholder shown when a nullable key number has no value. */
const NOT_AVAILABLE = "–";

/** The reason codes the UI has its own translated text for. */
type KnownReasonCode = "no_gain" | "no_move_after_reversal";

/**
 * Maps a backend reason code to the key segment of the "incomplete" message.
 * Unknown codes share the generic "other" text, which still shows `message`.
 */
function incompleteCode(reasonCode: string): KnownReasonCode | "other" {
  return reasonCode === "no_gain" || reasonCode === "no_move_after_reversal" ? reasonCode : "other";
}

/** The one-line verdict shown at the top of the result. */
function summaryText(result: ValveResult, t: Translate): string {
  if (result.reason_code !== "") {
    return t(`valve.result.incomplete.${incompleteCode(result.reason_code)}`, { message: result.reason });
  }
  if (result.deadband === null || result.deadband < DEADBAND_GOOD_PERCENT) {
    return t("valve.result.summaryGood");
  }
  return t("valve.result.summaryDeadband", { value: formatSignificant(result.deadband) });
}

/** One term/definition pair of the key-numbers list. */
function KeyNumber({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

/** The deadband value: a bracket when both bounds are known, a lower bound, or "none". */
function deadbandText(result: ValveResult, t: Translate): string {
  if (result.deadband_bracket !== null && result.deadband !== null) {
    const [low, high] = result.deadband_bracket;
    return t("valve.result.deadbandValue", {
      value: formatSignificant(result.deadband),
      low: formatSignificant(low),
      high: formatSignificant(high),
    });
  }
  if (result.deadband_lower_bound !== null) {
    return t("valve.result.deadbandAtLeast", { value: formatSignificant(result.deadband_lower_bound) });
  }
  return t("valve.result.deadbandNone");
}

/** The resolution cell, or "not detected" when the smallest move never showed up. */
function resolutionText(result: ValveResult, t: Translate): string {
  if (result.resolution_le === null) {
    return t("valve.result.resolutionNone");
  }
  return t("valve.result.resolutionValue", { value: formatSignificant(result.resolution_le) });
}

/** The gain cell, or a dash when it could not be estimated. */
function gainText(result: ValveResult, unit: string, t: Translate): string {
  if (result.gain === null) {
    return NOT_AVAILABLE;
  }
  return t("valve.result.gainValue", { value: formatSignificant(result.gain), unit });
}

/** The noise cell in PV units, or a dash when it could not be estimated. */
function noiseText(result: ValveResult, unit: string): string {
  return result.sigma_pv === null ? NOT_AVAILABLE : `${formatSignificant(result.sigma_pv)} ${unit}`;
}

/** Plain-language verdict, the key numbers of the test, and the charts. */
function ResultNumbers({ result, unit, t }: { result: ValveResult; unit: string; t: Translate }) {
  return (
    <dl className="key-numbers">
      <KeyNumber label={t("valve.result.deadband")} value={deadbandText(result, t)} />
      <KeyNumber label={t("valve.result.resolution")} value={resolutionText(result, t)} />
      <KeyNumber label={t("valve.result.gain")} value={gainText(result, unit, t)} />
      <KeyNumber label={t("valve.result.noise")} value={noiseText(result, unit)} />
    </dl>
  );
}

/** The collapsed table of detected OP steps and the PV response to each. */
function MovesTable({ analysis, t }: { analysis: ValveAnalysis; t: Translate }) {
  const moves = analysis.result.moves;
  return (
    <details>
      <summary>{t("valve.result.moves")}</summary>
      <table className="settings-table">
        <caption>{t("valve.result.moves")}</caption>
        <thead>
          <tr>
            <th scope="col">{t("valve.result.col.op")}</th>
            <th scope="col">{t("valve.result.col.pv")}</th>
            <th scope="col">{t("valve.result.col.moved")}</th>
          </tr>
        </thead>
        <tbody>
          {moves.map((move, index) => (
            // Moves carry no id from the backend, so the index identifies them.
            <tr key={index}>
              <td>{formatSignificant(move.op_change)}</td>
              <td>{move.pv_change === null ? NOT_AVAILABLE : formatSignificant(move.pv_change)}</td>
              <td>
                {move.moved
                  ? `✓ ${t("valve.result.moved.yes")}`
                  : `✗ ${t("valve.result.moved.no")}`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

/** The two panes (OP on top, PV below) sharing one x axis, in seconds since the first sample. */
function RecordCharts({ analysis, unit, t }: { analysis: ValveAnalysis; unit: string; t: Translate }) {
  const series = analysis.record.series;
  const timeLabel = `${t("trends.time")} (s)`;
  return (
    <>
      <TrendPane
        timeLabel={timeLabel}
        data={[series.t_s, series.op]}
        xIsTime={false}
        xLabel={timeLabel}
        syncKey={CHART_SYNC_KEY}
        height={CHART_HEIGHT}
        labels={[t("valve.result.chartOp")]}
        colors={[OP_COLOR]}
        unit={OP_UNIT}
      />
      <TrendPane
        timeLabel={timeLabel}
        data={[series.t_s, series.pv]}
        xIsTime={false}
        xLabel={timeLabel}
        syncKey={CHART_SYNC_KEY}
        height={CHART_HEIGHT}
        labels={[t("valve.result.chartPv")]}
        colors={[PV_COLOR]}
        unit={unit}
      />
    </>
  );
}

/**
 * Result view of a valve stroke test.
 *
 * A plain sentence says whether the valve passed, followed by the deadband,
 * resolution, gain and noise, the OP/PV charts and the detected steps.
 * The two callbacks restart the same plan or open the plan screen again.
 */
export function ValveResultView({
  analysis,
  loop,
  onAgain,
  onNewPlan,
  t,
}: {
  analysis: ValveAnalysis;
  loop: LoopSummary;
  onAgain: () => void;
  onNewPlan: () => void;
  t: Translate;
}) {
  const result = analysis.result;
  return (
    <section className="valve-result" aria-labelledby="valve-result-title">
      <h3 id="valve-result-title">{t("valve.result.title")}</h3>

      <p className="recommendation" role="status">
        {summaryText(result, t)}
      </p>

      {result.pv_left_band && (
        <p className="notice notice-warning" role="note">
          {t("valve.result.pvLeftBand")}
        </p>
      )}

      <ResultNumbers result={result} unit={loop.unit} t={t} />

      <RecordCharts analysis={analysis} unit={loop.unit} t={t} />

      <MovesTable analysis={analysis} t={t} />

      <p className="hint">{t("valve.result.caveat")}</p>

      <p>
        <button type="button" className="filter-chip" onClick={onAgain}>
          {t("valve.result.again")}
        </button>{" "}
        <button type="button" className="filter-chip" onClick={onNewPlan}>
          {t("valve.result.newPlan")}
        </button>
      </p>
    </section>
  );
}

// The two charts of a soft sensor run over the hours of the record. Chart 1: the estimate (and the
// bias-corrected one when it differs), the carry-forward baseline (the last lab value available) and
// the lab results as markers; stretches flagged out of range or extrapolation are shaded and the
// rule "do not use the estimate there" is printed next to it. Chart 2: the tracked bias with its drift
// limit; stretches with the drift flag raised are shaded. The numbers are also in the tables.
import type { LabRow, SoftSensorSeries } from "../api";
import type { Translate } from "../findings";
import { toHours } from "../anomaly";
import { carryForwardSeries, driftMask, labMarkers, unreliableMask } from "../softsensorSeries";
import { UNRELIABLE } from "../softsensor";
import { TrendPane } from "./TrendPane";

const CHART_HEIGHT_PX = 220;
const BIAS_HEIGHT_PX = 160;
const SYNC_KEY = "softsensor";
const DRIFT_SIGMAS = 2;

interface EstimateProps {
  series: SoftSensorSeries;
  labs: readonly LabRow[];
  labDelayS: number;
  t: Translate;
}

/** True when some value of the series is a number. */
function hasValues(values: readonly (number | null)[]): boolean {
  return values.some((value) => value !== null);
}

/** Estimate, baseline and lab markers; the corrected estimate only when it exists. */
export function EstimateChart({ series, labs, labDelayS, t }: EstimateProps) {
  const hours = series.t_s.map(toHours);
  const columns: [string, string, (number | null)[]][] = [
    [t("soft.chart.estimate"), "--series-1", series.estimate],
    [t("soft.chart.corrected"), "--series-3", series.corrected],
    [t("soft.chart.baseline"), "--series-2", carryForwardSeries(series.t_s, labs, labDelayS)],
    [t("soft.chart.lab"), "--series-4", labMarkers(series.t_s, labs)],
  ];
  const shown = columns.filter(([, , values], index) => index !== 1 || hasValues(values));
  const markerIndex = shown.length - 1;
  const flagged = series.validity.some((kind) => UNRELIABLE.includes(kind));
  return (
    <figure className="soft-chart" data-testid="soft-estimate-chart">
      <figcaption>{t("soft.chart.title.estimate")}</figcaption>
      <TrendPane
        data={[hours, ...shown.map(([, , values]) => values)]}
        labels={shown.map(([label]) => label)}
        colors={shown.map(([, color]) => color)}
        height={CHART_HEIGHT_PX}
        syncKey={SYNC_KEY}
        xIsTime={false}
        xLabel={t("soft.chart.axis")}
        mode={unreliableMask(series)}
        markerSeries={[markerIndex]}
      />
      <p className="hint">{t("soft.chart.flagsRule")}</p>
      {flagged && <p className="hint" data-testid="soft-flagged">{t("soft.chart.shadedUnreliable")}</p>}
    </figure>
  );
}

interface BiasProps {
  series: SoftSensorSeries;
  cvSigma: number | null;
  t: Translate;
}

/** The tracked bias with the drift limit (±2 cross-validated sigma) and shaded drift stretches. */
export function BiasChart({ series, cvSigma, t }: BiasProps) {
  const hours = series.t_s.map(toHours);
  const limit = cvSigma === null ? null : DRIFT_SIGMAS * cvSigma;
  const lines: [string, string, (number | null)[]][] = [[t("soft.chart.bias"), "--series-1", series.bias]];
  if (limit !== null) {
    lines.push([t("soft.chart.limitUpper"), "--series-2", hours.map(() => limit)]);
    lines.push([t("soft.chart.limitLower"), "--series-2", hours.map(() => -limit)]);
  }
  return (
    <figure className="soft-chart" data-testid="soft-bias-chart">
      <figcaption>{t("soft.chart.title.bias")}</figcaption>
      <TrendPane
        data={[hours, ...lines.map(([, , values]) => values)]}
        labels={lines.map(([label]) => label)}
        colors={lines.map(([, color]) => color)}
        height={BIAS_HEIGHT_PX}
        syncKey={SYNC_KEY}
        xIsTime={false}
        xLabel={t("soft.chart.axis")}
        mode={driftMask(series)}
      />
      {series.drift.some(Boolean) && <p className="hint">{t("soft.chart.shadedDrift")}</p>}
    </figure>
  );
}

// The T2 and SPE charts of a scan over the hours of the record. Each chart draws the statistic and
// its limit as a constant second series (TrendPane takes any number of series); stretches with an
// event are shaded through the band mask of the pane. The numbers are also in the events table.
import type { AnomalyEvent, AnomalySeries } from "../api";
import type { Translate } from "../findings";
import { eventMask, toHours } from "../anomaly";
import { TrendPane } from "./TrendPane";

const CHART_HEIGHT_PX = 170;
const SYNC_KEY = "anomaly";
const COLORS = ["--series-1", "--series-2"];

interface ChartProps {
  title: string;
  statistic: string;
  values: (number | null)[];
  limit: number;
  hours: number[];
  mask: number[];
  t: Translate;
}

/** One statistic with its limit line. */
function StatChart({ title, statistic, values, limit, hours, mask, t }: ChartProps) {
  const data = [hours, values, hours.map(() => limit)];
  return (
    <figure className="anomaly-chart">
      <figcaption>{title}</figcaption>
      <TrendPane
        data={data}
        labels={[statistic, t("anomaly.chart.limit")]}
        colors={COLORS}
        height={CHART_HEIGHT_PX}
        syncKey={SYNC_KEY}
        xIsTime={false}
        xLabel={t("anomaly.chart.axis")}
        mode={mask}
      />
    </figure>
  );
}

/** Both charts; an empty series draws nothing. */
export function AnomalyCharts({ series, events, t }: { series: AnomalySeries; events: readonly AnomalyEvent[]; t: Translate }) {
  if (series.t_s.length === 0) return null;
  const hours = series.t_s.map(toHours);
  const mask = eventMask(series.t_s, events);
  return (
    <div>
      <StatChart title={t("anomaly.chart.title.t2")} statistic={t("anomaly.chart.t2")} values={series.t2} limit={series.t2_limit} hours={hours} mask={mask} t={t} />
      <StatChart title={t("anomaly.chart.title.spe")} statistic={t("anomaly.chart.spe")} values={series.spe} limit={series.spe_limit} hours={hours} mask={mask} t={t} />
      {events.length > 0 && <p className="hint">{t("anomaly.chart.shaded")}</p>}
    </div>
  );
}

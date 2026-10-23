// Contribution bars of one event: the top tags by share of SPE and of T2 at the peak sample of
// the event. Shares are also written as numbers; they show where to look, not the cause.
import type { AnomalyEvent } from "../api";
import type { Translate } from "../findings";
import { formatPercent } from "../format";
import { topShares } from "../anomaly";
import { BarList } from "./AnomalyBars";

/** Bars of one statistic with its title. */
function ShareBars({ shares, label }: { shares: Record<string, number>; label: string }) {
  const rows = topShares(shares).map(([tag, share]) => ({ name: tag, fraction: share, text: formatPercent(share * 100, 1) }));
  return (
    <div className="contrib-column">
      <h4>{label}</h4>
      <BarList rows={rows} label={label} />
    </div>
  );
}

/** Both statistics side by side for the selected event (`number` is its 1-based position). */
export function AnomalyContributions({ event, number, t }: { event: AnomalyEvent; number: number; t: Translate }) {
  return (
    <section aria-label={t("anomaly.contrib.title", { n: number })} className="contrib">
      <h3>{t("anomaly.contrib.title", { n: number })}</h3>
      <p className="hint">{t("anomaly.contrib.hint")}</p>
      <div className="contrib-grid">
        <ShareBars shares={event.contributions.spe} label={t("anomaly.contrib.spe")} />
        <ShareBars shares={event.contributions.t2} label={t("anomaly.contrib.t2")} />
      </div>
    </section>
  );
}

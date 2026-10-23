// Model summary of the Anomalies page: number of components k, cumulative explained variance as a
// small bar list (the value is also text), the T2 and SPE limits, the training window and the
// short model hash.
import type { AnomalyModelSummary } from "../api";
import type { Translate } from "../findings";
import { formatFixed, formatPercent } from "../format";
import { shortHash, toHours } from "../anomaly";
import { BarList } from "./AnomalyBars";

const HOUR_DECIMALS = 2;
const LIMIT_DECIMALS = 2;
const PERCENT_DECIMALS = 1;

/** The fitted model, or the "not fitted" text. */
export function AnomalyModel({ model, t }: { model: AnomalyModelSummary | null; t: Translate }) {
  if (model === null) return <p className="status" data-testid="anomaly-no-model">{t("anomaly.model.none")}</p>;
  const bars = model.cumulative_variance.map((value, index) => ({
    name: t("anomaly.model.component", { n: index + 1 }),
    fraction: value,
    text: formatPercent(value * 100, PERCENT_DECIMALS),
  }));
  const trained = t("anomaly.model.trained", {
    start: formatFixed(toHours(model.window.start_s), HOUR_DECIMALS),
    end: formatFixed(toHours(model.window.end_s), HOUR_DECIMALS),
    dataset: model.dataset_id,
    rows: model.n_train,
  });
  return (
    <section aria-label={t("anomaly.model.title")}>
      <h3>{t("anomaly.model.title")}</h3>
      <dl className="advisory-config">
        <div><dt>{t("anomaly.model.components")}</dt><dd>{model.k}</dd></div>
        <div><dt>{t("anomaly.model.t2Limit")}</dt><dd>{formatFixed(model.t2_limit, LIMIT_DECIMALS)}</dd></div>
        <div><dt>{t("anomaly.model.speLimit")}</dt><dd>{formatFixed(model.spe_limit, LIMIT_DECIMALS)}</dd></div>
      </dl>
      <BarList label={t("anomaly.model.cumulative")} rows={bars} />
      <p className="hint">{trained}</p>
      <p className="hint">{t("anomaly.model.hash", { sha: shortHash(model.sha256) })}</p>
    </section>
  );
}

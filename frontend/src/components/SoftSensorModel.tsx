// Model summary of the Soft sensor page: chosen number of components, the cross-validated RMSE for
// each number of components as a small bar list (the value is also text), the cross-validated sigma,
// the training and domain row counts, R2 on the training rows, the training cut and the short hash.
import type { SoftSensorModelSummary } from "../api";
import type { Translate } from "../findings";
import { formatFixed, formatSignificant } from "../format";
import { shortHash } from "../softsensor";
import { toHours } from "../anomaly";
import { BarList } from "./AnomalyBars";

const HOUR_DECIMALS = 2;
const R2_DECIMALS = 3;
const MISSING = "--";

/** Bars of the cross-validated RMSE per number of components; the chosen number is marked. */
function cvBars(model: SoftSensorModelSummary, t: Translate) {
  const finite = model.cv_rmse.filter((value): value is number => value !== null);
  const largest = finite.length > 0 ? Math.max(...finite) : 1;
  return model.cv_rmse.map((value, index) => ({
    name: t("soft.model.component", { n: index + 1 }) + (index + 1 === model.chosen_components ? ` (${t("soft.model.chosen")})` : ""),
    fraction: value === null ? 0 : value / largest,
    text: value === null ? MISSING : formatSignificant(value),
  }));
}

/** The fitted model, or the "not fitted" text. */
export function SoftSensorModel({ model, t }: { model: SoftSensorModelSummary | null; t: Translate }) {
  if (model === null) return <p className="status" data-testid="soft-no-model">{t("soft.model.none")}</p>;
  const trained = t("soft.model.trained", {
    start: formatFixed(toHours(model.window.start_s), HOUR_DECIMALS),
    end: formatFixed(toHours(model.window.end_s), HOUR_DECIMALS),
    dataset: model.dataset_id,
  });
  return (
    <section aria-label={t("soft.model.title")}>
      <h3>{t("soft.model.title")}</h3>
      <dl className="advisory-config">
        <div><dt>{t("soft.model.chosenComponents")}</dt><dd>{model.chosen_components}</dd></div>
        <div><dt>{t("soft.model.cvSigma")}</dt><dd>{model.cv_sigma === null ? MISSING : formatSignificant(model.cv_sigma)}</dd></div>
        <div><dt>{t("soft.model.nTrain")}</dt><dd>{model.n_train}</dd></div>
        <div><dt>{t("soft.model.domainRows")}</dt><dd>{model.domain_rows}</dd></div>
        <div><dt>{t("soft.model.r2")}</dt><dd>{model.r2_train === null ? MISSING : formatFixed(model.r2_train, R2_DECIMALS)}</dd></div>
      </dl>
      <BarList label={t("soft.model.cv")} rows={cvBars(model, t)} />
      <p className="hint">{trained}</p>
      <p className="hint">{t("soft.model.hash", { sha: shortHash(model.sha256) })}</p>
    </section>
  );
}

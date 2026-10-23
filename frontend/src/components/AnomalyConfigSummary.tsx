// Read-only summary of an anomaly detector configuration: tags, model and event settings, and the
// mode, which is shown as "advisory only" (the schema allows no other active mode).
import type { AnomalyConfig } from "../api";
import type { Translate } from "../findings";

/** Frozen-protocol defaults, used when the stored config leaves a field out. */
const DEFAULTS = { variance: 0.9, alpha: 0.99, minConsecutive: 5, closeAfter: 10, samplePeriodS: 60 };

/** Rows for the dynamic lags and the stuck rule, only when the config has them. */
function optionalRows(config: AnomalyConfig, t: Translate): [string, string][] {
  const rows: [string, string][] = [];
  if (config.dynamic_lags !== undefined) rows.push([t("anomaly.config.dynamicLags"), String(config.dynamic_lags)]);
  if (config.stuck_samples !== undefined) {
    const value = config.stuck_samples === 0 ? t("anomaly.config.stuckOff") : String(config.stuck_samples);
    rows.push([t("anomaly.config.stuckSamples"), value]);
  }
  return rows;
}

/** The configuration as a definition list. */
export function AnomalyConfigSummary({ config, t }: { config: AnomalyConfig; t: Translate }) {
  const rows: [string, string][] = [
    [t("anomaly.config.mode"), config.mode === "advisory" ? t("anomaly.mode.advisory") : t("anomaly.mode.off")],
    [t("anomaly.config.tags"), config.tags.join(", ")],
    [t("anomaly.config.varianceFraction"), String(config.variance_fraction ?? DEFAULTS.variance)],
    [t("anomaly.config.alpha"), String(config.alpha ?? DEFAULTS.alpha)],
    ...optionalRows(config, t),
    [t("anomaly.config.minConsecutive"), String(config.min_consecutive ?? DEFAULTS.minConsecutive)],
    [t("anomaly.config.closeAfter"), String(config.close_after ?? DEFAULTS.closeAfter)],
    [t("anomaly.config.samplePeriod"), t("anomaly.config.seconds", { value: config.sample_period_s ?? DEFAULTS.samplePeriodS })],
  ];
  return (
    <section aria-label={t("anomaly.config.title")}>
      <h3>{t("anomaly.config.title")}</h3>
      {config.description !== undefined && config.description !== "" && <p className="hint">{config.description}</p>}
      <dl className="advisory-config">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

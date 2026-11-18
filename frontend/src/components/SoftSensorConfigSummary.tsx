// Read-only summary of a soft sensor configuration: target label, input tags, lags, lab delay and
// the mode, which is shown as "advisory only" (the schema allows no other active mode).
import type { SoftSensorConfig } from "../api";
import type { Translate } from "../findings";
import { DEFAULT_LAGS_S, DEFAULT_LAB_DELAY_S, DEFAULT_SAMPLE_PERIOD_S } from "../softsensor";

const DEFAULT_MAX_COMPONENTS = 8;
const DEFAULT_CV_BLOCKS = 5;
const PERCENT = 100;

/** The reference inputs as one line each, or "none"; the coverage is shown in per cent. */
function referencesText(config: SoftSensorConfig, t: Translate): string {
  const refs = config.reference_inputs ?? [];
  if (refs.length === 0) return t("soft.config.none");
  return refs
    .map((r) => t("soft.config.referenceItem", {
      tag: r.tag, window: r.window_s, shift: r.shift_s, coverage: Number((r.min_coverage * PERCENT).toFixed(1)), weight: r.bias_weight,
    }))
    .join("; ");
}

/** The backup mode as one line: the measured tag and its validity rules, or "none". */
function backupText(config: SoftSensorConfig, t: Translate): string {
  const b = config.backup;
  if (b === undefined || !b.enabled) return t("soft.config.none");
  return t("soft.config.backupItem", {
    tag: b.measured_tag ?? "", frozen: b.frozen_s ?? 0, lo: b.range_lo ?? 0, hi: b.range_hi ?? 0, hold: b.return_hold_s ?? 0,
  });
}

/** The configuration as a definition list. */
export function SoftSensorConfigSummary({ config, t }: { config: SoftSensorConfig; t: Translate }) {
  const seconds = (value: number) => t("soft.config.seconds", { value });
  const rows: [string, string][] = [
    [t("soft.config.mode"), config.mode === "advisory" ? t("soft.mode.advisory") : t("soft.mode.off")],
    [t("soft.config.target"), config.target_tag],
    [t("soft.config.inputs"), config.input_tags.join(", ")],
    [t("soft.config.lags"), (config.lags_s ?? DEFAULT_LAGS_S).map(seconds).join(", ")],
    [t("soft.config.labDelay"), seconds(config.lab_delay_s ?? DEFAULT_LAB_DELAY_S)],
    [t("soft.config.samplePeriod"), seconds(config.sample_period_s ?? DEFAULT_SAMPLE_PERIOD_S)],
    [t("soft.config.maxComponents"), String(config.max_components ?? DEFAULT_MAX_COMPONENTS)],
    [t("soft.config.cvBlocks"), String(config.cv_blocks ?? DEFAULT_CV_BLOCKS)],
    [t("soft.config.references"), referencesText(config, t)],
    [t("soft.config.backup"), backupText(config, t)],
  ];
  return (
    <section aria-label={t("soft.config.title")}>
      <h3>{t("soft.config.title")}</h3>
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

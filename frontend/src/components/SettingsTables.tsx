// src/components/SettingsTables.tsx

import type { TuningPayload, TuningSettings } from "../api";
import type { Translate } from "../findings";
import { formatDcs, formatSignificant } from "../format";

/**
 * Format a number with four significant digits.
 *
 * Trailing zeros are dropped, so 23.879239 becomes "23.88" and 0.0659783
 * becomes "0.06598". Used for every value shown in the tuning tables.
 */
export function formatNumber(value: number): string {
  return formatSignificant(value);
}

/** Tuning constants of the PI controller, per rule (AMIGO is null for integrating loops). */
type PiSettings = TuningSettings;

/**
 * Render the PI tuning constants of the SIMC and AMIGO rules.
 *
 * `kc` is the proportional gain, `ti_s` the integral time in seconds.
 */
export function PiSettingsTable({ settings, t }: { settings: PiSettings; t: Translate }) {
  // The rule name is shown as-is, so the table reads like the tuning sheet.
  const rules: Array<{ label: string; values: { kc: number; ti_s: number } }> = [
    { label: "SIMC", values: settings.simc },
  ];
  if (settings.amigo !== null) rules.push({ label: "AMIGO", values: settings.amigo });

  return (
    <table className="settings-table">
      <thead>
        <tr>
          <th>{t("tuning.settings.rule")}</th>
          <th>{t("tuning.settings.kc")}</th>
          <th>{t("tuning.settings.ti")}</th>
        </tr>
      </thead>
      <tbody>
        {rules.map((rule) => (
          <tr key={rule.label}>
            <th scope="row">{rule.label}</th>
            <td>{formatNumber(rule.values.kc)}</td>
            <td>{formatNumber(rule.values.ti_s)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * Render one definition list of key numbers for a single DCS form.
 *
 * The keys are shown raw (for example "integral_time_min") so they can be
 * matched against the DCS documentation.
 */
function DcsForm({ formName, values, t }: { formName: string; values: Record<string, number>; t: Translate }) {
  return (
    <section className="dcs-form">
      <h4>{t(`tuning.dcs.${formName}`)}</h4>
      <dl className="key-numbers">
        {Object.entries(values).map(([key, value]) => (
          <div key={key}>
            <dt>{key}</dt>
            <dd>{formatDcs(value)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/**
 * Render the key numbers of every DCS form.
 *
 * Returns null when there is no form to show, so the caller can render this
 * unconditionally.
 */
export function DcsForms({ forms, t }: { forms: Record<string, Record<string, number>>; t: Translate }) {
  const formEntries = Object.entries(forms);
  if (formEntries.length === 0) {
    return null;
  }

  return (
    <div className="dcs-forms">
      {formEntries.map(([formName, values]) => (
        <DcsForm key={formName} formName={formName} values={values} t={t} />
      ))}
    </div>
  );
}

/**
 * Render the parameter names of the loop's PID vendor block with the values to type in.
 *
 * Returns null when the loop has no vendor set or the payload has no block for it.
 */
export function VendorBlock({ payload, t }: { payload: Partial<Pick<TuningPayload, "vendor" | "vendor_forms">>; t: Translate }) {
  const spec = payload.vendor ? payload.vendor_forms?.[payload.vendor] : undefined;
  if (!spec) return null;
  return (
    <div className="vendor-block">
      <h4>{t("tuning.vendor.title", { block: spec.block })}</h4>
      <p className="field-help">{t(`tuning.vendor.evidence.${spec.evidence}`)}</p>
      <dl className="dcs-form">
        {Object.entries(spec.tags).map(([tag, value]) => (
          <div key={tag}>
            <dt>{tag}</dt>
            <dd>{typeof value === "number" ? formatNumber(value) : String(value)}</dd>
          </div>
        ))}
      </dl>
      <ul>
        {spec.caveats.map((caveat) => (
          <li key={caveat}>{caveat}</li>
        ))}
      </ul>
    </div>
  );
}

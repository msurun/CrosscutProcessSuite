// src/components/ValveSettingsForm.tsx
//
// Form for the valve step-test settings. Labels, help texts and the per-field error are
// provided through `t`; the parent owns the field values and the validation state.

import type { Translate } from "../findings";
import type { Settings } from "../valveTest";

/** Decimal keyboard hint for numeric inputs; both decimal points and commas are typed. */
const DECIMAL_INPUT_MODE = "decimal";

/** Keys of the settings shown inside the collapsible "advanced" section. */
const ADVANCED_FIELDS: ReadonlyArray<keyof Settings> = ["stepSizes", "stepsPerLeg"];

/** Props shared by every labelled input in this form. */
interface FieldProps {
  id: string;
  label: string;
  help?: string;
  value: string;
  isInvalid: boolean;
  invalidMessage: string;
  onChange: (value: string) => void;
}

/**
 * One labelled decimal input with optional help text and a per-field error.
 *
 * The help id is derived from `id` so the input can be linked with aria-describedby.
 */
function ValveField({ id, label, help, value, isInvalid, invalidMessage, onChange }: FieldProps) {
  const helpId = `${id}-help`;
  return (
    <label className="field" htmlFor={id}>
      <span className="field-label">{label}</span>
      <input
        id={id}
        className="field-input"
        inputMode={DECIMAL_INPUT_MODE}
        type="text"
        value={value}
        aria-invalid={isInvalid}
        aria-describedby={help !== undefined ? helpId : undefined}
        onChange={(event) => onChange(event.target.value)}
      />
      {help !== undefined && (
        <small className="field-help" id={helpId}>
          {help}
        </small>
      )}
      {isInvalid && (
        <p className="status status-error" role="alert">
          {invalidMessage}
        </p>
      )}
    </label>
  );
}

/** True when the advanced section must start open to reveal the field the user must fix. */
function shouldOpenAdvanced(invalidField: keyof Settings | null): boolean {
  return invalidField !== null && ADVANCED_FIELDS.includes(invalidField);
}

/**
 * Form for the valve step-test settings.
 *
 * Renders a short intro, the five main fields and an advanced section with the step sizes and
 * steps per leg. Pressing the submit button calls `onSubmit`; the parent sends the request.
 */
export function ValveSettingsForm({
  settings,
  invalidField,
  busy,
  onChange,
  onSubmit,
  t,
}: {
  settings: Settings;
  invalidField: keyof Settings | null;
  busy: boolean;
  onChange: (key: keyof Settings, value: string) => void;
  onSubmit: () => void;
  t: Translate;
}) {
  const invalidMessage = t("valve.settings.invalid");

  /** Render one field bound to the settings key, wired to the shared invalid message. */
  const renderField = (id: string, key: keyof Settings, label: string, help?: string) => (
    <ValveField
      id={id}
      label={label}
      help={help}
      value={settings[key]}
      isInvalid={invalidField === key}
      invalidMessage={invalidMessage}
      onChange={(value) => onChange(key, value)}
    />
  );

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <p className="valve-intro">{t("valve.intro")}</p>

      {renderField(
        "valve-op-start",
        "opStart",
        t("valve.settings.opStart"),
        t("valve.settings.opStartHelp"),
      )}
      {renderField(
        "valve-dwell",
        "dwellS",
        t("valve.settings.dwell"),
        t("valve.settings.dwellHelp"),
      )}
      {renderField("valve-op-low", "opLow", t("valve.settings.opLow"))}
      {renderField("valve-op-high", "opHigh", t("valve.settings.opHigh"))}
      {renderField(
        "valve-pv-band",
        "pvBand",
        t("valve.settings.pvBand"),
        t("valve.settings.pvBandHelp"),
      )}

      <details className="valve-advanced" open={shouldOpenAdvanced(invalidField)}>
        <summary>{t("valve.settings.advanced")}</summary>
        {renderField(
          "valve-step-sizes",
          "stepSizes",
          t("valve.settings.stepSizes"),
          t("valve.settings.stepSizesHelp"),
        )}
        {renderField("valve-steps-per-leg", "stepsPerLeg", t("valve.settings.stepsPerLeg"))}
      </details>

      <p className="form-actions">
        <button type="submit" className="filter-chip" disabled={busy}>
          {busy ? t("valve.settings.creating") : t("valve.settings.create")}
        </button>
      </p>
    </form>
  );
}

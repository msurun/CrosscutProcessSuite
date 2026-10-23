// src/components/TuningIpdt.tsx
// Pieces of the tuning page that belong to integrating (level) loops: the ramp model view, the
// refusal view with plain-language reasons, the recommendation text, the averaging-level inputs
// and the warning banners (including the button that saves the process kind).

import { useState } from "react";

import { saveKnowledge, type IpdtModel, type TuningPayload, type TuningSettings, type TuningWarning } from "../api";
import type { Translate } from "../findings";
import { formatFixed } from "../format";
import { isIpdtModel, isWideDelayRange, parseSwing, reasonActionKey, reasonKey, type SwingInput } from "../tuningIpdt";
import { formatNumber } from "./SettingsTables";

/** Model view of an integrating loop: ramp slope and dead time, no gain or time constant. */
export function IpdtModelView({
  model,
  unit,
  spanS,
  t,
}: {
  model: IpdtModel;
  unit: string;
  spanS: number;
  t: Translate;
}) {
  return (
    <>
      <dl className="key-numbers">
        <dt>{t("tuning.ipdt.slope")}</dt>
        <dd>
          {formatNumber(model.slope_per_s)} <span className="unit">{t("tuning.ipdt.slopeUnit", { unit })}</span>
        </dd>
        <dt>{t("tuning.model.delay")}</dt>
        <dd>
          {t("tuning.ipdt.delayRange", {
            value: formatNumber(model.delay_s),
            lower: formatNumber(model.delay_lower_s),
            upper: formatNumber(model.delay_upper_s),
          })}
        </dd>
      </dl>
      {isWideDelayRange(model, spanS) && (
        <p className="notice notice-warning" role="note">
          {t("tuning.ipdt.delayWide")}
        </p>
      )}
      <p className="hint">{t("tuning.ipdt.explain")}</p>
      {model.verdict === "low_confidence" && (
        <div className="notice notice-warning" role="note">
          <p>{t("tuning.ipdt.lowConfidence")}</p>
          <ul>
            {model.reasons.map((code) => (
              <li key={code}>{t(reasonKey(code))}</li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}

/** Refusal view: every reason code in plain language with what to do about it. */
export function IpdtRefusal({ reasons, t }: { reasons: string[]; t: Translate }) {
  return (
    <div className="notice notice-warning" role="alert">
      <p>{t("tuning.blocked.ipdt_refused")}</p>
      <ul className="ipdt-reasons">
        {reasons.map((code) => (
          <li key={code}>
            <strong>{t(reasonKey(code))}</strong> {t(reasonActionKey(code))}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Recommendation sentence for the integrating case, the overshoot note and the action hint. */
export function IpdtRecommendation({
  payload,
  settings,
  fitText,
  t,
}: {
  payload: TuningPayload;
  settings: TuningSettings;
  fitText: string;
  t: Translate;
}) {
  const tauC = payload.tau_c_s === undefined ? "" : formatNumber(payload.tau_c_s);
  const upper = isIpdtModel(payload.model) ? formatNumber(payload.model.delay_used_s) : "";
  return (
    <>
      <p className="recommendation" role="status">
        {t("tuning.recommendation.ipdt", {
          kc: formatNumber(settings.simc.kc),
          ti: formatNumber(settings.simc.ti_s),
          tauc: tauC,
          upper,
          fit: fitText,
        })}
      </p>
      <p className="notice notice-warning" role="note">
        {t("tuning.ipdt.experimental")}
      </p>
      <p className="banner" role="note">
        {t("tuning.ipdt.overshoot")}
      </p>
      {payload.invert_control === true && (
        <p className="notice notice-warning" role="note">
          {t("tuning.ipdt.reverse")}
        </p>
      )}
    </>
  );
}

/** The optional averaging-level input pair; both fields or none, both positive. */
export function SwingInputs({
  maxText,
  loadText,
  onChange,
  tauC,
  unit,
  t,
}: {
  maxText: string;
  loadText: string;
  onChange: (maxText: string, loadText: string) => void;
  tauC: number | undefined;
  unit: string;
  t: Translate;
}) {
  const input: SwingInput = parseSwing(maxText, loadText);
  const message = input.state === "invalid" ? t(`tuning.swing.invalid.${input.error}`) : null;
  return (
    <fieldset className="swing-inputs">
      <legend>{t("tuning.swing.title")}</legend>
      <p className="hint">{t("tuning.swing.intro")}</p>
      <label className="field-label">
        {t("tuning.swing.max", { unit })}
        <input
          className="field-input"
          type="text"
          inputMode="decimal"
          value={maxText}
          aria-invalid={message !== null}
          onChange={(event) => onChange(event.target.value, loadText)}
        />
      </label>
      <label className="field-label">
        {t("tuning.swing.load")}
        <input
          className="field-input"
          type="text"
          inputMode="decimal"
          value={loadText}
          aria-invalid={message !== null}
          onChange={(event) => onChange(maxText, event.target.value)}
        />
      </label>
      {message !== null && (
        <p className="status status-error" role="alert">
          {message}
        </p>
      )}
      {input.state === "valid" && tauC !== undefined && (
        <p role="status">{t("tuning.swing.result", { tauc: formatNumber(tauC) })}</p>
      )}
    </fieldset>
  );
}

/** Button with an in-page confirmation that saves "integrating" as the loop's process kind. */
function SetIntegratingAction({
  datasetId,
  loopName,
  onSaved,
  t,
}: {
  datasetId: string;
  loopName: string;
  onSaved: () => void;
  t: Translate;
}) {
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const confirm = (): void => {
    saveKnowledge(datasetId, loopName, { process_kind: "integrating" })
      .then(() => {
        setAsking(false);
        onSaved();
      })
      .catch((reason: unknown) => setError(String(reason)));
  };
  if (!asking) {
    return (
      <button type="button" className="filter-chip" onClick={() => setAsking(true)}>
        {t("tuning.warning.setIntegrating")}
      </button>
    );
  }
  return (
    <div role="group" aria-label={t("tuning.warning.setIntegrating")}>
      <p>{t("tuning.warning.setIntegratingConfirm")}</p>
      <button type="button" className="filter-chip" onClick={confirm}>
        {t("tuning.warning.setIntegratingYes")}
      </button>{" "}
      <button type="button" className="filter-chip" onClick={() => setAsking(false)}>
        {t("tuning.warning.setIntegratingNo")}
      </button>
      {error !== null && (
        <p className="status status-error" role="alert">
          {t("trends.error", { reason: error })}
        </p>
      )}
    </div>
  );
}

/** Text of one warning, with the numbers it carries. */
function warningText(warning: TuningWarning, t: Translate): string {
  if (warning.code === "looks_integrating") {
    const reason = t(`tuning.warning.looks_integrating.${warning.reason}`, {
      tau: warning.time_constant_s === null ? "" : formatNumber(warning.time_constant_s),
      r2: warning.ipdt_r_squared === null ? "" : formatFixed(warning.ipdt_r_squared, 2),
    });
    return `${t("tuning.warning.looks_integrating")} ${reason}`;
  }
  if (warning.code === "looks_self_regulating") {
    return t("tuning.warning.looks_self_regulating", { r2: formatFixed(warning.fopdt_r_squared, 2) });
  }
  return t(`tuning.warning.${warning.code}`);
}

/** All warnings of the payload: errors as before, `looks_integrating` with its action, info banners. */
export function TuningWarnings({
  warnings,
  datasetId,
  loopName,
  onKindSaved,
  t,
}: {
  warnings: TuningWarning[];
  datasetId: string;
  loopName: string;
  onKindSaved: () => void;
  t: Translate;
}) {
  return (
    <>
      {warnings.map((warning) => {
        const text = warningText(warning, t);
        if (warning.code === "looks_integrating") {
          return (
            <div key={warning.code} className="notice notice-warning" role="note">
              <p>{text}</p>
              <SetIntegratingAction datasetId={datasetId} loopName={loopName} onSaved={onKindSaved} t={t} />
            </div>
          );
        }
        if (warning.code === "looks_self_regulating") {
          return (
            <p key={warning.code} className="banner" role="note">
              {text}
            </p>
          );
        }
        return (
          <p key={warning.code} className="status status-error">
            {text}
          </p>
        );
      })}
    </>
  );
}

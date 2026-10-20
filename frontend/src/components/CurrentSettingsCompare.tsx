// src/components/CurrentSettingsCompare.tsx
// Lets the user type the Kc and Ti values currently active in the plant and
// see, per tuning rule, how far the proposed values are from them.
// The typed values are remembered in localStorage when the browser allows it.

import { useEffect, useState } from "react";
import type { Translate } from "../findings";
import { formatNumber } from "./SettingsTables";

/** Values currently active in the plant, as typed by the user. */
type CurrentValues = { kc: number; ti: number };

/** A proposed value and its signed change in percent, already formatted. */
type Change = { proposed: number; changePercent: number };

/** Percentage change beyond which the plant value is reported as "differs". */
const CLOSE_THRESHOLD_PERCENT = 10;

/** Decimal places kept when showing a percentage change. */
const CHANGE_DECIMALS = 1;

/**
 * Sign a percentage and format it with one decimal and a space before "%",
 * e.g. "+12.5 %", "-3.0 %" or "0.0 %".
 */
export function formatChange(changePercent: number): string {
  const rounded = changePercent.toFixed(CHANGE_DECIMALS);
  // toFixed turns -0.04 into "-0.0", which would read as a negative change.
  const normalised = Number(rounded) === 0 ? "0.0" : rounded;
  const sign = Number(normalised) > 0 ? "+" : "";
  return `${sign}${normalised} %`;
}

/**
 * Percentage change from `current` to `proposed`: (proposed - current) / current * 100.
 *
 * Raises when `current` is zero or negative, because the relative change is
 * undefined there and a silent Infinity would hide the mistake.
 */
export function relativeChange(current: number, proposed: number): number {
  if (!(current > 0)) {
    throw new RangeError(`current must be greater than zero, got ${current}`);
  }
  return ((proposed - current) / current) * 100;
}

/**
 * Parse a user-typed positive number; a decimal comma is accepted as "3,5".
 *
 * Returns null unless the text is a finite number greater than zero, so blank
 * and out-of-range inputs are treated the same way by the caller.
 */
export function parsePositive(text: string): number | null {
  const normalised = text.trim().replace(",", ".");
  if (normalised === "") {
    return null;
  }
  const value = Number(normalised);
  if (!Number.isFinite(value) || value <= 0) {
    return null;
  }
  return value;
}

/** Read the stored values; null when absent, malformed or storage is blocked. */
function readStoredValues(storageKey: string): CurrentValues | null {
  try {
    const raw = localStorage.getItem(storageKey);
    if (raw === null) {
      return null;
    }
    const parsed: unknown = JSON.parse(raw);
    if (!isStoredValues(parsed)) {
      return null;
    }
    return { kc: parsed.kc, ti: parsed.ti };
  } catch {
    return null;
  }
}

/** True when the parsed JSON has the shape {kc: number, ti: number}. */
function isStoredValues(value: unknown): value is CurrentValues {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return typeof candidate.kc === "number" && typeof candidate.ti === "number";
}

/** Write the values; a blocked or full storage must not break the form. */
function writeStoredValues(storageKey: string, values: CurrentValues): void {
  try {
    localStorage.setItem(storageKey, JSON.stringify(values));
  } catch {
    // Storage is optional: the comparison still works without it.
  }
}

/** Input for one current value plus, when the text is blank or invalid, a message. */
function CurrentField({
  label,
  text,
  isInvalid,
  onChange,
  errorText,
}: {
  label: string;
  text: string;
  isInvalid: boolean;
  onChange: (text: string) => void;
  errorText: string;
}) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <input
        className="field-input"
        inputMode="decimal"
        value={text}
        aria-invalid={isInvalid}
        onChange={(event) => onChange(event.target.value)}
      />
      {isInvalid ? (
        <span className="field-error" role="alert">
          {errorText}
        </span>
      ) : null}
    </label>
  );
}

/** Value and change of Kc and Ti for one rule, ready for the table cells. */
function ruleChanges(
  proposed: { kc: number; ti_s: number },
  current: CurrentValues,
): { kc: Change; ti: Change } {
  return {
    kc: { proposed: proposed.kc, changePercent: relativeChange(current.kc, proposed.kc) },
    ti: { proposed: proposed.ti_s, changePercent: relativeChange(current.ti, proposed.ti_s) },
  };
}

/** A change is close when its absolute value stays within the threshold. */
function isClose(changePercent: number): boolean {
  return Math.abs(changePercent) <= CLOSE_THRESHOLD_PERCENT;
}

/**
 * Details panel comparing the proposed PI settings with values the user typed.
 *
 * `storageKey` identifies the localStorage entry holding {kc, ti}; the panel
 * works without storage, it just does not remember the values.
 */
export function CurrentSettingsCompare({
  storageKey,
  settings,
  t,
}: {
  storageKey: string;
  settings: { simc: { kc: number; ti_s: number }; amigo: { kc: number; ti_s: number } };
  t: Translate;
}) {
  const [kcText, setKcText] = useState("");
  const [tiText, setTiText] = useState("");

  // Load once on mount; a later storageKey change is not expected in one page.
  useEffect(() => {
    const stored = readStoredValues(storageKey);
    if (stored !== null) {
      setKcText(String(stored.kc));
      setTiText(String(stored.ti));
    }
  }, [storageKey]);

  const currentKc = parsePositive(kcText);
  const currentTi = parsePositive(tiText);

  /** Remember the pair whenever both inputs hold valid values. */
  const rememberValues = (kc: number | null, ti: number | null): void => {
    if (kc !== null && ti !== null) {
      writeStoredValues(storageKey, { kc, ti });
    }
  };

  const handleKcChange = (text: string): void => {
    setKcText(text);
    rememberValues(parsePositive(text), currentTi);
  };

  const handleTiChange = (text: string): void => {
    setTiText(text);
    rememberValues(currentKc, parsePositive(text));
  };

  // Blank text is simply "not filled in yet"; non-blank text that fails to
  // parse is the only case the user is warned about.
  const isKcInvalid = kcText.trim() !== "" && currentKc === null;
  const isTiInvalid = tiText.trim() !== "" && currentTi === null;
  const hasBothValues = currentKc !== null && currentTi !== null;

  return (
    <details className="current-compare">
      <summary>{t("tuning.current.title")}</summary>
      <p>{t("tuning.current.intro")}</p>
      <div className="current-inputs">
        <CurrentField
          label={t("tuning.current.kc")}
          text={kcText}
          isInvalid={isKcInvalid}
          onChange={handleKcChange}
          errorText={t("tuning.current.invalid")}
        />
        <CurrentField
          label={t("tuning.current.ti")}
          text={tiText}
          isInvalid={isTiInvalid}
          onChange={handleTiChange}
          errorText={t("tuning.current.invalid")}
        />
      </div>
      {hasBothValues ? (
        <ComparisonTable
          settings={settings}
          current={{ kc: currentKc, ti: currentTi }}
          t={t}
        />
      ) : null}
    </details>
  );
}

/** Table of proposed values and their changes, plus the closeness status line. */
function ComparisonTable({
  settings,
  current,
  t,
}: {
  settings: { simc: { kc: number; ti_s: number }; amigo: { kc: number; ti_s: number } };
  current: CurrentValues;
  t: Translate;
}) {
  const simc = ruleChanges(settings.simc, current);
  const amigo = ruleChanges(settings.amigo, current);
  const isSimcClose = isClose(simc.kc.changePercent) && isClose(simc.ti.changePercent);

  return (
    <>
      <table className="settings-table">
        <caption className="visually-hidden">{t("tuning.current.proposed")}</caption>
        <thead>
          <tr>
            <th>{t("tuning.settings.rule")}</th>
            <th>{t("tuning.settings.kc")}</th>
            <th>{t("tuning.current.change")}</th>
            <th>{t("tuning.settings.ti")}</th>
            <th>{t("tuning.current.change")}</th>
          </tr>
        </thead>
        <tbody>
          <ChangeRow label="SIMC" kc={simc.kc} ti={simc.ti} />
          <ChangeRow label="AMIGO" kc={amigo.kc} ti={amigo.ti} />
        </tbody>
      </table>
      <p role="status">{isSimcClose ? t("tuning.current.close") : t("tuning.current.differs")}</p>
    </>
  );
}

/** One table row: rule name, then proposed value and change for Kc and Ti. */
function ChangeRow({ label, kc, ti }: { label: string; kc: Change; ti: Change }) {
  return (
    <tr>
      <th scope="row">{label}</th>
      <td>{formatNumber(kc.proposed)}</td>
      <td>{formatChange(kc.changePercent)}</td>
      <td>{formatNumber(ti.proposed)}</td>
      <td>{formatChange(ti.changePercent)}</td>
    </tr>
  );
}

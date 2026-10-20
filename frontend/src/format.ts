// Single home for turning numbers into display strings in the user's language.
// The UI language lives on <html lang>: read it at call time, never at import,
// so tests and runtime language switches both work. No dependencies beyond Intl.
// Non-finite values render as an en dash so tables never show "NaN".
const DASH = "–";

/**
 * The current UI language, or `undefined` to let the browser pick its default.
 * An empty `lang` attribute means "not set", which is what we pass through.
 */
function currentLanguage(): string | undefined {
  const lang = document.documentElement.lang;
  return lang === "" ? undefined : lang;
}

/**
 * Format a number with a fixed count of significant digits, no grouping.
 * Uses the locale's decimal separator (comma in pl, point in en).
 */
export function formatSignificant(value: number, digits = 4): string {
  if (!Number.isFinite(value)) {
    return DASH;
  }
  return new Intl.NumberFormat(currentLanguage(), {
    maximumSignificantDigits: digits,
    useGrouping: false,
  }).format(value);
}

/**
 * Format a number with an exact number of fraction digits, no grouping.
 * A value that rounds to zero (e.g. -0.04 at 1 decimal) shows no minus sign:
 * "-0.0" is never printed, only "0.0".
 */
export function formatFixed(value: number, decimals: number): string {
  if (!Number.isFinite(value)) {
    return DASH;
  }
  const formatted = new Intl.NumberFormat(currentLanguage(), {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
    useGrouping: false,
  }).format(value);
  return isZeroAfterRounding(value, decimals) ? formatted.replace("-", "") : formatted;
}

/**
 * Like {@link formatFixed}, but shows an explicit "+" for positive results
 * (checked after rounding). Zero carries no sign, negatives keep the minus.
 */
export function formatSigned(value: number, decimals: number): string {
  if (!Number.isFinite(value)) {
    return DASH;
  }
  const formatted = formatFixed(value, decimals);
  const shouldShowPlus = !isZeroAfterRounding(value, decimals) && value > 0;
  return shouldShowPlus ? `+${formatted}` : formatted;
}

/**
 * Format a DCS value: always a dot decimal, 4 significant digits, no grouping,
 * regardless of the UI language. The round-trip through Number/toPrecision keeps
 * the typed value faithful to what the device will receive.
 */
export function formatDcs(value: number): string {
  if (!Number.isFinite(value)) {
    return DASH;
  }
  return Number(value.toPrecision(4)).toString();
}

/**
 * Format a number as a percentage cell: fixed decimals plus a space and "%".
 */
export function formatPercent(value: number, decimals = 0): string {
  return `${formatFixed(value, decimals)} %`;
}

/**
 * Whether `value` becomes zero once rounded to `decimals` fraction digits.
 * Used to decide if a minus sign must be dropped from the output.
 */
function isZeroAfterRounding(value: number, decimals: number): boolean {
  const scale = 10 ** decimals;
  return Math.round(value * scale) === 0;
}

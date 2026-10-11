/**
 * Translation catalogues and locale-aware formatting helpers.
 *
 * A language is just a flat JSON file in `./locales/<code>.json` mapping a key to a
 * string that may contain `{name}` placeholders. Adding a language means adding a
 * file: no registry to update.
 */

/** A flat map of translation keys to strings, e.g. `{ "greeting": "Hello {name}" }`. */
export type Catalogue = Record<string, string>;

/** Language used when nothing else matches. Every app must ship this catalogue. */
export const FALLBACK_LANGUAGE = "en";

const PLACEHOLDER_PATTERN = /\{(\w+)\}/g;
const SUBTAG_SEPARATOR = "-";
const DEFAULT_FRACTION_DIGITS = 1;
const MILLISECONDS_PER_SECOND = 1000;

/** Every catalogue in `./locales`, keyed by file name without extension. */
const catalogues = import.meta.glob("./locales/*.json", {
  eager: true,
  import: "default",
}) as Record<string, Catalogue>;

/** Turns `./locales/pt-BR.json` into `pt-BR`. */
function fileNameToLanguage(path: string): string {
  const fileName = path.slice(path.lastIndexOf("/") + 1);
  return fileName.replace(/\.json$/, "");
}

/** Catalogues keyed by language code instead of file path. */
const cataloguesByLanguage: Record<string, Catalogue> = Object.fromEntries(
  Object.entries(catalogues).map(([path, catalogue]) => [fileNameToLanguage(path), catalogue]),
);

/** Returns the sorted list of language codes that have a catalogue. */
export function availableLanguages(): string[] {
  return Object.keys(cataloguesByLanguage).sort();
}

/** Returns the catalogue for a language, or an empty one when the language is unknown. */
function catalogueFor(language: string): Catalogue {
  return cataloguesByLanguage[language] ?? {};
}

/** Replaces every `{name}` in a template; missing params keep the placeholder as-is. */
function fillPlaceholders(template: string, params: Record<string, string | number>): string {
  return template.replace(PLACEHOLDER_PATTERN, (placeholder, name: string) => {
    const value = params[name];
    return value === undefined ? placeholder : String(value);
  });
}

/**
 * Returns the translation of `key` for `language`.
 *
 * Looks in the language catalogue, then in English, then returns `key` itself, so a
 * missing translation shows something usable instead of throwing.
 */
export function translate(
  language: string,
  key: string,
  params: Record<string, string | number> = {},
): string {
  const catalogue = catalogueFor(language);
  const fallback = catalogueFor(FALLBACK_LANGUAGE);
  const template = catalogue[key] ?? fallback[key] ?? key;
  return fillPlaceholders(template, params);
}

/** Formats a number for a language, e.g. `1,5` in English and `1,5`/`1.5` per locale rules. */
export function formatNumber(
  language: string,
  value: number,
  fractionDigits: number = DEFAULT_FRACTION_DIGITS,
): string {
  return new Intl.NumberFormat(language, {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(value);
}

/** Formats an epoch (seconds) as the language's short date and medium time, in UTC. */
export function formatDateTime(language: string, epochSeconds: number): string {
  const date = new Date(epochSeconds * MILLISECONDS_PER_SECOND);
  return new Intl.DateTimeFormat(language, {
    dateStyle: "short",
    timeStyle: "medium",
    timeZone: "UTC",
  }).format(date);
}

/** Returns the primary subtag of a BCP 47 tag, e.g. `pt-BR` -> `pt`. */
function primarySubtag(tag: string): string {
  return tag.split(SUBTAG_SEPARATOR)[0].toLowerCase();
}

/**
 * Picks a language from the user's `preferred` tags that is available.
 *
 * Compares only primary subtags, so `pt-BR` matches an available `pt`. Falls back to
 * `FALLBACK_LANGUAGE` when nothing matches.
 */
export function detectLanguage(preferred: readonly string[], available: readonly string[]): string {
  const availablePrimarySubtags = new Set(available.map(primarySubtag));
  const match = preferred.find((tag) => availablePrimarySubtags.has(primarySubtag(tag)));
  return match === undefined ? FALLBACK_LANGUAGE : available.find((code) => primarySubtag(code) === primarySubtag(match))!;
}

/**
 * Turns the structural differences between two rule bases into sentences
 * in the chosen language.
 */

import type { FuzzyChange } from "./api";
import type { Translate } from "./findings";

/** Compact UTC timestamp `YYYYMMDDTHHMMSSffffffZ` produced by the backend. */
const VERSION_ID_PATTERN = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})\d{6}Z$/;

/** Placeholder used for translation parameters that do not apply to a change. */
const NOT_APPLICABLE = "";

/** Names of the fuzzy term shapes, as the backend spells them. */
interface TermShape {
  shape: string;
  params: number[];
}

/** Human label for a version id; unmatched ids are returned unchanged. */
export function versionLabel(versionId: string): string {
  const match = VERSION_ID_PATTERN.exec(versionId);
  if (match === null) {
    return versionId;
  }
  const [, year, month, day, hour, minute, second] = match;
  return `${year}-${month}-${day} ${hour}:${minute}:${second} UTC`;
}

/** Build the translation parameters for one change, using an empty string where a value does not apply. */
function changeParams(change: FuzzyChange): Record<string, string | number> {
  return {
    variable: change.variable ?? NOT_APPLICABLE,
    term: change.term ?? NOT_APPLICABLE,
    rule: change.rule ?? NOT_APPLICABLE,
    old: formatOldValue(change),
    new: formatNewValue(change),
    fields: formatChangedFields(change.fields),
  };
}

/** Format the `old` side: a range as "low..high", a term as "shape(p, p)", anything else as "". */
function formatOldValue(change: FuzzyChange): string {
  if (change.code === "range_changed") {
    return formatRange(change.old);
  }
  if (change.code === "term_changed") {
    return formatTerm(change.old);
  }
  return NOT_APPLICABLE;
}

/** Format the `new` side, with the same rules as {@link formatOldValue}. */
function formatNewValue(change: FuzzyChange): string {
  if (change.code === "range_changed") {
    return formatRange(change.new);
  }
  if (change.code === "term_changed") {
    return formatTerm(change.new);
  }
  return NOT_APPLICABLE;
}

/** True when `value` is an array of two numbers, the backend shape of a range. */
function isNumberPair(value: unknown): value is [number, number] {
  return Array.isArray(value) && value.length === 2 && value.every((item) => typeof item === "number");
}

/** Render a `[low, high]` pair as "low..high", or "" when the value is not a pair. */
function formatRange(value: unknown): string {
  if (!isNumberPair(value)) {
    return NOT_APPLICABLE;
  }
  const [low, high] = value;
  return `${low}..${high}`;
}

/** True when `value` is a `{shape, params}` object, the backend shape of a fuzzy term. */
function isTermShape(value: unknown): value is TermShape {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as { shape?: unknown; params?: unknown };
  return typeof candidate.shape === "string" && Array.isArray(candidate.params);
}

/** Render a `{shape, params}` term as "tri(0, 5, 10)", or "" when the value is not a term. */
function formatTerm(value: unknown): string {
  if (!isTermShape(value)) {
    return NOT_APPLICABLE;
  }
  return `${value.shape}(${value.params.join(", ")})`;
}

/** Translate each changed field name and join them with ", "; an empty list becomes "". */
function formatChangedFields(fields: string[] | undefined): string {
  if (fields === undefined || fields.length === 0) {
    return NOT_APPLICABLE;
  }
  return fields.map((name) => name).join(", ");
}

/** Sentence for one structural change, e.g. "Variable added: temperature". */
export function changeText(t: Translate, change: FuzzyChange): string {
  return t(`fuzzy.change.${change.code}`, changeParams(change));
}

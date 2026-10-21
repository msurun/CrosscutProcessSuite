/**
 * Display names of fuzzy rule-base parts, translated through the locale files.
 *
 * The stored document keeps its own (English) text. Texts of the bundled example systems are
 * looked up by system id / variable id / term id; text that differs from the bundled English
 * original (user-made or edited) is shown unchanged.
 */

import type { Translate } from "./findings";
import { FALLBACK_LANGUAGE, translate } from "./i18n";

const SYSTEM_PREFIX = "fuzzy.names.system";
const VARIABLE_PREFIX = "fuzzy.names.var";
const TERM_PREFIX = "fuzzy.names.term";

/** Translation of `key`, or `undefined` when the active catalogues have no entry for it. */
function lookup(t: Translate, key: string): string | undefined {
  const text = t(key);
  return text === key ? undefined : text;
}

/** Translation of `key` only when `original` is still the bundled English text of that key. */
function lookupIfOriginal(t: Translate, key: string, original: string): string {
  const english = translate(FALLBACK_LANGUAGE, key);
  return english === original ? (lookup(t, key) ?? original) : original;
}

/** Display name of a rule base; `fallback` is the document's own name. */
export function systemName(t: Translate, systemId: string, fallback: string): string {
  return lookupIfOriginal(t, `${SYSTEM_PREFIX}.${systemId}.name`, fallback);
}

/** Display description of a rule base; `fallback` is the document's own description. */
export function systemDescription(t: Translate, systemId: string, fallback: string): string {
  return lookupIfOriginal(t, `${SYSTEM_PREFIX}.${systemId}.description`, fallback);
}

/** Display label of a variable: translated example label, the document's label, or its id. */
export function variableLabel(t: Translate, variable: { id: string; label?: string }): string {
  const key = `${VARIABLE_PREFIX}.${variable.id}`;
  if (variable.label === undefined) return lookup(t, key) ?? variable.id;
  return lookupIfOriginal(t, key, variable.label);
}

/** Display name of a term of a variable; unknown terms keep their stored name. */
export function termLabel(t: Translate, variableId: string, termName: string): string {
  return lookup(t, `${TERM_PREFIX}.${variableId}.${termName}`) ?? termName;
}

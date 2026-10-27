// src/components/knowledgeDraft.ts
//
// Pure helpers of the knowledge editor: parsing the text fields, building the update payload,
// checking the ranges and describing what a save changed. No React in here.

import type { LoopKnowledgeUpdate, LoopKnowledgeValues } from "../api";

/** Result of parsing one numeric field: the value, "not given" for blank, or "invalid". */
export type NumberField = number | null | "invalid";

/** Names of the positive-only numeric fields. */
export const NUMERIC_FIELDS = ["delay_s", "ultimate_period_s", "amplitude_limit"] as const;

/** Names of the range fields, which accept zero and negative numbers. */
export const RANGE_FIELDS = ["pv_eng_min", "pv_eng_max", "out_eng_min", "out_eng_max"] as const;

export type NumericFieldName = (typeof NUMERIC_FIELDS)[number];
export type RangeFieldName = (typeof RANGE_FIELDS)[number];
export type DraftFieldName = NumericFieldName | RangeFieldName;

/** The fields the user edits, all as text so a decimal comma can be typed. */
export type KnowledgeDraft = Record<DraftFieldName, string> & {
  process_kind: LoopKnowledgeValues["process_kind"];
  /** "" = not set. */
  vendor: "" | NonNullable<LoopKnowledgeValues["vendor"]>;
};

/** One changed field: its key, the old and new value (null = not given / cleared). */
export interface FieldChange {
  name: keyof LoopKnowledgeValues;
  before: LoopKnowledgeValues[keyof LoopKnowledgeValues];
  after: LoopKnowledgeValues[keyof LoopKnowledgeValues];
}

/** Parse a number text: blank is null, a decimal comma is accepted, non-finite is "invalid". */
function parseFinite(text: string): NumberField {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  const value = Number(trimmed.replace(",", "."));
  return Number.isFinite(value) ? value : "invalid";
}

/** Parse a positive-only field ("invalid" for zero, negatives and text). */
export function parseNumberField(text: string): NumberField {
  const value = parseFinite(text);
  return value === "invalid" || (value !== null && value <= 0) ? "invalid" : value;
}

/** Parse a range field: any finite number, including zero and negatives. */
export function parseRangeField(text: string): NumberField {
  return parseFinite(text);
}

/** The parser that belongs to a field name. */
function parserFor(name: DraftFieldName): (text: string) => NumberField {
  return (RANGE_FIELDS as readonly string[]).includes(name) ? parseRangeField : parseNumberField;
}

/** True when the text of the named field is blank or valid for that field. */
export function isDraftFieldValid(draft: KnowledgeDraft, name: DraftFieldName): boolean {
  return parserFor(name)(draft[name]) !== "invalid";
}

/** True when every numeric and range text of the draft parses. */
export function isDraftValid(draft: KnowledgeDraft): boolean {
  return [...NUMERIC_FIELDS, ...RANGE_FIELDS].every((name) => isDraftFieldValid(draft, name));
}

/** True when min and max are both given and min >= max. */
function isInverted(min: string, max: string): boolean {
  const low = parseRangeField(min);
  const high = parseRangeField(max);
  return typeof low === "number" && typeof high === "number" && low >= high;
}

/** Which ranges ("pv" / "out") have their minimum at or above their maximum. */
export function invertedRanges(draft: KnowledgeDraft): Array<"pv" | "out"> {
  const result: Array<"pv" | "out"> = [];
  if (isInverted(draft.pv_eng_min, draft.pv_eng_max)) result.push("pv");
  if (isInverted(draft.out_eng_min, draft.out_eng_max)) result.push("out");
  return result;
}

/** Build the update payload with only the fields that differ from the loaded values. */
export function buildUpdate(loaded: LoopKnowledgeValues, draft: KnowledgeDraft): LoopKnowledgeUpdate {
  const update: Record<string, number | null | string> = {};
  for (const name of [...NUMERIC_FIELDS, ...RANGE_FIELDS]) {
    const parsed = parserFor(name)(draft[name]);
    if (parsed !== "invalid" && parsed !== loaded[name]) update[name] = parsed;
  }
  if (draft.process_kind !== loaded.process_kind) update.process_kind = draft.process_kind;
  if ((draft.vendor || null) !== loaded.vendor) update.vendor = draft.vendor || null;
  return update as LoopKnowledgeUpdate;
}

/** The text shown in the inputs for the loaded values; null becomes a blank input. */
export function draftFromValues(values: LoopKnowledgeValues): KnowledgeDraft {
  const text = (value: number | null): string => (value === null ? "" : String(value));
  const draft = { process_kind: values.process_kind, vendor: values.vendor ?? "" } as KnowledgeDraft;
  for (const name of [...NUMERIC_FIELDS, ...RANGE_FIELDS]) draft[name] = text(values[name]);
  return draft;
}

/** True when the draft holds at least one value that differs from the loaded values. */
export function hasChanges(loaded: LoopKnowledgeValues, draft: KnowledgeDraft): boolean {
  return Object.keys(buildUpdate(loaded, draft)).length > 0;
}

/** The fields whose value differs between two saved states, in display order. */
export function diffValues(before: LoopKnowledgeValues, after: LoopKnowledgeValues): FieldChange[] {
  const names = [...NUMERIC_FIELDS, ...RANGE_FIELDS, "process_kind", "vendor"] as const;
  return names
    .filter((name) => before[name] !== after[name])
    .map((name) => ({ name, before: before[name], after: after[name] }));
}

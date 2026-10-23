// Pure helpers of the Import view: the default mapping from the server's guesses, the dataset id
// check, the request mapping, error classification and chart data. No React, so they are tested alone.
import { ApiError, type IntakeCheck, type IntakeMapping, type IntakeOptions, type IntakePreview, type IntakeVerdict } from "./api";
import type { StatusLevel } from "./components/StatusChip";
import type { Translate } from "./findings";

/** Largest CSV the application reads (the server refuses more), in bytes. */
export const MAX_CSV_BYTES = 25_000_000;
/** The id pattern the server enforces for dataset and loop names. */
const ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;
/** Every mapping field the form can hold; the empty string means "not given". */
export const MAPPING_FIELDS = [
  "time_col", "pv_col", "out_col", "sp_col", "mode_col", "tag_col", "value_col", "tag_pv", "tag_out", "tag_sp", "tag_mode",
] as const;
/** Name of one mapping field. */
export type MappingField = (typeof MAPPING_FIELDS)[number];
/** The mapping as the form holds it: every field a string. */
export type MappingForm = Record<MappingField, string>;

/** The mapping pre-filled from the server's `suggestions` (a missing guess stays empty). */
export function defaultMapping(preview: IntakePreview): MappingForm {
  const form = {} as MappingForm;
  for (const field of MAPPING_FIELDS) form[field] = preview.suggestions[field] ?? "";
  return form;
}

/** The detected delimiter, decimal and time format as the options the user may edit. */
export function defaultOptions(preview: IntakePreview): IntakeOptions {
  return { time_format: preview.time_format, decimal: preview.decimal, delimiter: preview.delimiter };
}

/** The signals the check needs, by layout. */
export function requiredFields(layout: IntakePreview["layout"]): MappingField[] {
  return layout === "long"
    ? ["time_col", "tag_col", "value_col", "tag_pv", "tag_out"]
    : ["time_col", "pv_col", "out_col"];
}

/** Request mapping: only the fields of the layout in use that were given. */
export function mappingBody(form: MappingForm, layout: IntakePreview["layout"]): IntakeMapping {
  const wide: MappingField[] = ["time_col", "pv_col", "out_col", "sp_col", "mode_col"];
  const long: MappingField[] = ["time_col", "tag_col", "value_col", "tag_pv", "tag_out", "tag_sp", "tag_mode"];
  const body: IntakeMapping = {};
  for (const field of layout === "long" ? long : wide) if (form[field] !== "") body[field] = form[field];
  return body;
}

/** True when every required field of the layout is chosen. */
export function mappingComplete(form: MappingForm, layout: IntakePreview["layout"]): boolean {
  return requiredFields(layout).every((field) => form[field] !== "");
}

/** Why an id is not acceptable (the string is the `import.id.<code>` key part), or null when it is. */
export type IdError = "empty" | "pattern" | "underscore";

/** Checks a dataset id the way the server does: letters, digits, `_` and `-`, 1 to 64, not starting with `_`. */
export function datasetIdError(id: string): IdError | null {
  if (id === "") return "empty";
  if (!ID_PATTERN.test(id)) return "pattern";
  if (id.startsWith("_")) return "underscore";
  return null;
}

/** True when a loop name matches the server pattern. */
export function loopNameValid(name: string): boolean {
  return ID_PATTERN.test(name);
}

/** Icon-and-word level of a verdict. */
export function verdictLevel(verdict: IntakeVerdict): StatusLevel {
  if (verdict === "ready") return "ok";
  return verdict === "usable_with_warnings" ? "warning" : "problem";
}

/** True when a dataset may be created from the check. */
export function canCreate(check: IntakeCheck | null): boolean {
  return check !== null && check.verdict !== "not_usable";
}

/** Message for any thrown value: translated for 409, 413 and a refused record, else the server text. */
export function describeIntakeError(error: unknown, t: Translate): string {
  if (!(error instanceof ApiError)) return t("import.error.network", { detail: error instanceof Error ? error.message : String(error) });
  if (error.status === 409) return t("import.error.exists");
  if (error.status === 413) return t("import.error.tooLarge");
  if (error.status === 422 && error.findingCodes.length > 0) {
    return t("import.error.notUsable", { codes: error.findingCodes.join(", ") });
  }
  if (error.status === 422) return t("import.error.unprocessable", { detail: error.message });
  return t("import.error.other", { detail: error.message });
}

/** The chart columns [t (min), PV, OUT] of the sample; time in minutes from the start. */
export function sampleColumns(check: IntakeCheck): { minutes: number[]; pv: (number | null)[]; out: (number | null)[] } {
  return { minutes: check.sample.t_s.map((s) => s / 60), pv: check.sample.pv, out: check.sample.out };
}

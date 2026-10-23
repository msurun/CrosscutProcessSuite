// Translated wording of the Import view: the check's findings (by code, with their figures), the
// "read as" and assumption lines (by code) and the dry-run reasons. The server sends English text
// next to every code; that text is the fallback for a code or figure this client does not know.
import type { IntakeFinding, IntakeNote } from "./api";
import type { Translate } from "./findings";
import { formatFixed, formatPercent, formatSignificant } from "./format";
import { KNOWN_IPDT_REASONS } from "./tuningIpdt";

const SECONDS_PER_MINUTE = 60;
const DELIMITER_NAMES: Record<string, string> = { "\t": "tab", ";": "semicolon", ",": "comma", "|": "pipe" };
type Params = Record<string, unknown>;
type Texts = { text: string; todo: string };

/** Human name of a delimiter character. */
export function delimiterName(delimiter: string, t: Translate): string {
  return delimiter in DELIMITER_NAMES ? t(`import.delim.${DELIMITER_NAMES[delimiter]}`) : delimiter;
}

/** A finite number from the params, or null when it is missing or of another type. */
function num(params: Params, key: string): number | null {
  const value = params[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Seconds as minutes with one decimal. */
function minutes(seconds: number): string {
  return `${formatFixed(seconds / SECONDS_PER_MINUTE, 1)} min`;
}

/** Numbers of the params as the figures a message needs; null when one is missing. */
function figures(params: Params, keys: string[], show: (name: string, value: number) => string): Record<string, string> | null {
  const out: Record<string, string> = {};
  for (const key of keys) {
    const value = num(params, key);
    if (value === null) return null;
    out[key] = show(key, value);
  }
  return out;
}

/** The translated reason of a dry run: the wizard's own text for a known code, else the code as sent. */
export function reasonText(reason: string, t: Translate): string {
  if (KNOWN_IPDT_REASONS.includes(reason)) return t(`tuning.ipdt.reason.${reason}`);
  return reason === "malformed_input" ? t("import.reason.malformed_input") : reason;
}

/** Share (0 to 1) as a whole percent, a time in seconds as minutes, anything else with 3 digits. */
function showFigure(name: string, value: number): string {
  if (name.endsWith("share")) return formatPercent(value * 100, 0);
  return name.endsWith("_s") ? minutes(value) : formatSignificant(value, 3);
}

/** Message values of a finding by code, or null when its figures are missing. */
function findingValues(finding: IntakeFinding, t: Translate): Record<string, string> | null {
  const p: Params = finding.params ?? {};
  switch (finding.code) {
    case "lead_too_short": return figures(p, ["share", "lead_s", "min_share", "need_s"], showFigure);
    case "post_move_too_short": return postValues(p, t);
    case "not_in_manual": return figures(p, ["share"], showFigure);
    case "bad_values": return figures(p, ["count"], (_, v) => String(v));
    case "pv_coarse": return figures(p, ["resolution", "range"], showFigure);
    case "no_out_move": return figures(p, ["min_range"], showFigure);
    case "low_confidence": return Array.isArray(p.reasons) ? { reasons: p.reasons.map((r) => reasonText(String(r), t)).join(", ") } : null;
    case "uneven_sampling": return {};
    default: return null;
  }
}

/** Values of the post-move finding: time recorded, time needed, why that much, and the unknown-dead-time note. */
function postValues(p: Params, t: Translate): Record<string, string> | null {
  const base = figures(p, ["post_s", "need_s"], showFigure);
  if (base === null) return null;
  const basis = t(p.basis === "fit" ? "import.finding.post.basisFit" : "import.finding.post.basisFloor");
  return { ...base, basis, unknown: p.known === false ? ` ${t("import.finding.post.unknown")}` : "" };
}

/** Title line and what-to-do line of a finding in the user's language (the server's English if unknown). */
export function findingTexts(finding: IntakeFinding, t: Translate): Texts {
  const values = findingValues(finding, t);
  if (values === null) return { text: finding.text, todo: finding.what_to_do };
  const closed = finding.code === "not_in_manual" && (finding.params ?? {}).closed_loop === true;
  const text = t(`import.finding.${finding.code}.text`, values) + (closed ? ` ${t("import.finding.not_in_manual.closed")}` : "");
  const todo = t(`import.finding.${finding.code}.todo`, values);
  return { text, todo };
}

/** Message values of a note by code, or null when its figures are missing. */
function noteValues(note: IntakeNote, t: Translate): Record<string, string> | null {
  const p: Params = note.params ?? {};
  const time = t(`import.note.time.${String(p.time)}`);
  const decimal = t(p.decimal === "," ? "import.decimal.comma" : "import.decimal.dot");
  const delimiter = delimiterName(String(p.delimiter ?? ""), t);
  switch (note.code) {
    case "read_wide": return { time, decimal, delimiter };
    case "read_long": return num(p, "tags") === null ? null : { tags: String(p.tags), time, decimal, delimiter };
    case "tz_utc": return { start: String(p.start ?? "") };
    case "units": return { pv: String(p.pv ?? ""), out: String(p.out ?? "") };
    case "resampling": return figures(p, ["step_s"], (_, v) => formatSignificant(v, 4));
    case "relative_anchor": case "no_sp": case "no_mode": return {};
    default: return null;
  }
}

/** One "read as" or assumption line in the user's language (the server's English if the code is unknown). */
export function noteText(note: IntakeNote, t: Translate): string {
  const values = noteValues(note, t);
  return values === null ? note.text : t(`import.note.${note.code}`, values);
}

/** The lines to show: the coded notes when the server sent them, else its plain texts. */
export function noteLines(notes: IntakeNote[] | undefined, plain: string[], t: Translate): string[] {
  return notes === undefined ? plain : notes.map((note) => noteText(note, t));
}

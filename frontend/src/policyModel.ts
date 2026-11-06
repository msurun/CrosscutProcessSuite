// frontend/src/policyModel.ts
/**
 * Pure domain logic and validation for Write Gateway write policies (ADR 013, issues #46/#47).
 * Encapsulates engineering limit validation, diff analysis (loosening vs tightening),
 * and safety risk summaries without DOM or network dependencies.
 */

export type GatewayOperatingMode = "off" | "advisory" | "dry_run" | "confirm" | "supervised";

export const POLICY_MODES: readonly GatewayOperatingMode[] = [
  "off",
  "advisory",
  "dry_run",
  "confirm",
  "supervised",
];

export const STANDARD_LOOP_MODES: readonly string[] = ["CAS", "AUTO", "RSP", "MAN"];
export const TAG_PATTERN = /^[A-Za-z0-9_.:-]+$/;
export const MAX_TAG_LENGTH = 128;
export const MAX_REASONABLE_MAGNITUDE = 1e12;

export interface TargetPolicy {
  limits: [number, number];
  max_step: number;
  max_rate_per_s: number;
  min_interval_s: number;
  allowed_loop_modes: string[];
  hold_off_s: number;
  watchdog_s: number;
  readback_tolerance: number;
  [key: string]: unknown;
}

export interface PolicyDocument {
  version: 1;
  mode: GatewayOperatingMode;
  targets: Record<string, TargetPolicy>;
  [key: string]: unknown;
}

export interface PolicyPinInfo {
  digest: string;
  author: string;
  approver: string;
  approved_at: string;
}

export interface FieldChange {
  field: string;
  oldValue: unknown;
  newValue: unknown;
  loosening: boolean;
  explanation: string;
  /** Placeholder values for the explanation text. */
  params: Record<string, string | number>;
}

export interface TargetDiff {
  tag: string;
  status: "added" | "removed" | "modified" | "unchanged";
  changes: FieldChange[];
  loosening: boolean;
}

export interface PolicyDiff {
  modeChange: FieldChange | null;
  targetDiffs: TargetDiff[];
  extraFieldChanges: FieldChange[];
  hasChanges: boolean;
  hasLoosening: boolean;
}

export interface RiskSummary {
  level: "high" | "medium" | "low" | "none";
  looseningCount: number;
  tighteningCount: number;
  addedTargets: number;
  removedTargets: number;
  modifiedTargets: number;
  modeChanged: boolean;
}

/**
 * Checks if a string contains Unicode lookalikes (homoglyphs) or non-ASCII characters.
 *
 * In plain words:
 * Industrial tag identifiers in DCS/SCADA architectures must be ASCII to prevent
 * confusable tag spoofing (e.g. Cyrillic 'а' replacing Latin 'a').
 */
export function hasUnicodeLookalikes(text: string): boolean {
  // Non-ASCII characters: codepoints above 127
  return /[^\x20-\x7E]/.test(text);
}

/**
 * Validates a target tag identifier string against DCS naming constraints.
 */
export function validateTag(
  tag: string,
  existingTags: readonly string[],
  currentTag?: string,
): string | null {
  const trimmed = tag.trim();
  if (trimmed.length === 0) return "policy.validation.required";
  if (trimmed.length > MAX_TAG_LENGTH) return "policy.validation.tooLarge";
  if (!TAG_PATTERN.test(trimmed)) return "policy.validation.tagInvalid";
  const isDuplicate = existingTags.some(
    (existing) => existing === trimmed && existing !== currentTag,
  );
  if (isDuplicate) return "policy.validation.tagDuplicate";
  return null;
}

/**
 * Validates finite number constraints and boundary magnitude for numeric inputs.
 */
export function validateFiniteNumber(value: unknown): string | null {
  if (typeof value !== "number" || !Number.isFinite(value) || Number.isNaN(value)) {
    return "policy.validation.finiteNumber";
  }
  if (Math.abs(value) > MAX_REASONABLE_MAGNITUDE) {
    return "policy.validation.tooLarge";
  }
  return null;
}

/**
 * Validates strictly positive (> 0) numeric fields (e.g. max_step, max_rate, watchdog).
 */
export function validatePositiveNumber(value: unknown): string | null {
  const finiteErr = validateFiniteNumber(value);
  if (finiteErr) return finiteErr;
  return (value as number) <= 0 ? "policy.validation.positive" : null;
}

/**
 * Validates non-negative (>= 0) numeric fields (e.g. min_interval, hold_off, readback_tolerance).
 */
export function validateNonNegativeNumber(value: unknown): string | null {
  const finiteErr = validateFiniteNumber(value);
  if (finiteErr) return finiteErr;
  return (value as number) < 0 ? "policy.validation.nonNegative" : null;
}

/**
 * Validates range limits [low, high]: finite, non-null, and low <= high.
 */
export function validateLimits(limits: unknown): string | null {
  if (!Array.isArray(limits) || limits.length !== 2) {
    return "policy.validation.required";
  }
  const lowErr = validateFiniteNumber(limits[0]);
  if (lowErr) return lowErr;
  const highErr = validateFiniteNumber(limits[1]);
  if (highErr) return highErr;
  if (limits[0] > limits[1]) {
    return "policy.validation.limitsOrder";
  }
  return null;
}

/**
 * Validates loop modes array: non-empty, unique strings, each trimmed length > 0.
 */
export function validateLoopModes(modes: unknown): string | null {
  if (!Array.isArray(modes) || modes.length === 0) {
    return "policy.validation.allowedModesEmpty";
  }
  const unique = new Set<string>();
  for (const item of modes) {
    if (typeof item !== "string" || item.trim().length === 0) {
      return "policy.validation.allowedModesEmpty";
    }
    if (unique.has(item.trim())) {
      return "policy.validation.tagDuplicate";
    }
    unique.add(item.trim());
  }
  return null;
}

/**
 * Validates all fields of a TargetPolicy matching write-policy.schema.json rules.
 */
export function validateTarget(target: TargetPolicy): Record<string, string> {
  const errors: Record<string, string> = {};
  const limitsErr = validateLimits(target.limits);
  if (limitsErr) errors.limits = limitsErr;
  const stepErr = validatePositiveNumber(target.max_step);
  if (stepErr) errors.max_step = stepErr;
  const rateErr = validatePositiveNumber(target.max_rate_per_s);
  if (rateErr) errors.max_rate_per_s = rateErr;
  const intervalErr = validateNonNegativeNumber(target.min_interval_s);
  if (intervalErr) errors.min_interval_s = intervalErr;
  const modesErr = validateLoopModes(target.allowed_loop_modes);
  if (modesErr) errors.allowed_loop_modes = modesErr;
  const holdOffErr = validateNonNegativeNumber(target.hold_off_s);
  if (holdOffErr) errors.hold_off_s = holdOffErr;
  const watchdogErr = validatePositiveNumber(target.watchdog_s);
  if (watchdogErr) errors.watchdog_s = watchdogErr;
  const tolErr = validateNonNegativeNumber(target.readback_tolerance);
  if (tolErr) errors.readback_tolerance = tolErr;
  return errors;
}

/**
 * Parses the raw text of a number input. Empty or non-numeric text gives NaN (never 0, so a
 * cleared field stays invalid); exponent notation ("1e-3") is accepted; Infinity becomes NaN
 * (rejected by validation); negative zero is normalised to 0.
 */
export function parseNumberInput(raw: string): number {
  if (raw.trim() === "") return Number.NaN;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) return Number.NaN;
  return parsed === 0 ? 0 : parsed;
}

/**
 * Normalises an actor name exactly like the server's two-person comparison:
 * NFKC, collapse whitespace, strip, casefold, NFKC again.
 */
export function normalizeActor(name: string): string {
  const collapsed = name.normalize("NFKC").split(/\s+/).filter(Boolean).join(" ");
  return collapsed.toUpperCase().toLowerCase().normalize("NFKC");
}

/** True when two actor names are the same person under the server's normalisation. */
export function sameActor(a: string | null | undefined, b: string | null | undefined): boolean {
  if (!a || !b) return false;
  return normalizeActor(a) === normalizeActor(b);
}

/** JSON text with object keys sorted, so key order never makes equal documents differ. */
export function stableStringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  if (typeof value === "number" && !Number.isFinite(value)) return `"${String(value)}"`;
  if (typeof value === "object" && value !== null) {
    const record = value as Record<string, unknown>;
    const entries = Object.keys(record).sort().map((k) => `${JSON.stringify(k)}:${stableStringify(record[k])}`);
    return `{${entries.join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

/** Deep equality of two policy documents (key order independent, NaN-safe). */
export function docsEqual(a: PolicyDocument | null, b: PolicyDocument | null): boolean {
  return stableStringify(a) === stableStringify(b);
}

type Params = Record<string, string | number>;

interface ChangeSpec {
  field: string;
  keyBase: string;
  oldValue: unknown;
  newValue: unknown;
  loosening: boolean;
  params: Params;
}

function makeChange(spec: ChangeSpec): FieldChange {
  const { keyBase, ...rest } = spec;
  return { ...rest, explanation: `policy.diff.${keyBase}${spec.loosening ? "Loosening" : "Tightening"}` };
}

function diffMode(oldMode: GatewayOperatingMode, newMode: GatewayOperatingMode): FieldChange | null {
  if (oldMode === newMode) return null;
  const oldIdx = POLICY_MODES.indexOf(oldMode);
  const newIdx = POLICY_MODES.indexOf(newMode);
  // An unknown mode is never treated as safe.
  const loosening = oldIdx < 0 || newIdx < 0 || newIdx > oldIdx;
  return makeChange({ field: "mode", keyBase: "mode", oldValue: oldMode, newValue: newMode, loosening, params: { oldMode, newMode } });
}

function diffLimits(oldLim: [number, number], newLim: [number, number]): FieldChange | null {
  if (oldLim[0] === newLim[0] && oldLim[1] === newLim[1]) return null;
  const loosening = newLim[0] < oldLim[0] || newLim[1] > oldLim[1];
  const params = { oldLo: oldLim[0], oldHi: oldLim[1], newLo: newLim[0], newHi: newLim[1] };
  return makeChange({ field: "limits", keyBase: "limits", oldValue: oldLim, newValue: newLim, loosening, params });
}

interface ScalarSpec {
  field: string;
  keyBase: string;
  /** Which direction widens write authority. */
  looserWhenBigger: boolean;
}

const MAX_STEP: ScalarSpec = { field: "max_step", keyBase: "maxStep", looserWhenBigger: true };
const MAX_RATE: ScalarSpec = { field: "max_rate_per_s", keyBase: "maxRate", looserWhenBigger: true };
const MIN_INTERVAL: ScalarSpec = { field: "min_interval_s", keyBase: "minInterval", looserWhenBigger: false };
const HOLD_OFF: ScalarSpec = { field: "hold_off_s", keyBase: "holdOff", looserWhenBigger: false };
const WATCHDOG: ScalarSpec = { field: "watchdog_s", keyBase: "watchdog", looserWhenBigger: true };
const READBACK_TOL: ScalarSpec = { field: "readback_tolerance", keyBase: "readbackTol", looserWhenBigger: true };

function diffScalar(spec: ScalarSpec, oldVal: number, newVal: number): FieldChange | null {
  if (oldVal === newVal) return null;
  const loosening = spec.looserWhenBigger ? newVal > oldVal : newVal < oldVal;
  return makeChange({ field: spec.field, keyBase: spec.keyBase, oldValue: oldVal, newValue: newVal, loosening, params: { oldVal, newVal } });
}

function diffAllowedModes(oldModes: string[], newModes: string[]): FieldChange | null {
  const added = newModes.filter((m) => !oldModes.includes(m));
  const removed = oldModes.filter((m) => !newModes.includes(m));
  if (added.length === 0 && removed.length === 0) return null;
  const params = { added: added.join(", ") || "-", removed: removed.join(", ") || "-" };
  return makeChange({ field: "allowed_loop_modes", keyBase: "modes", oldValue: oldModes, newValue: newModes, loosening: added.length > 0, params });
}

function compareTargetFields(oldT: TargetPolicy, newT: TargetPolicy): FieldChange[] {
  const changes: (FieldChange | null)[] = [
    diffLimits(oldT.limits, newT.limits),
    diffScalar(MAX_STEP, oldT.max_step, newT.max_step),
    diffScalar(MAX_RATE, oldT.max_rate_per_s, newT.max_rate_per_s),
    diffScalar(MIN_INTERVAL, oldT.min_interval_s, newT.min_interval_s),
    diffAllowedModes(oldT.allowed_loop_modes, newT.allowed_loop_modes),
    diffScalar(HOLD_OFF, oldT.hold_off_s, newT.hold_off_s),
    diffScalar(WATCHDOG, oldT.watchdog_s, newT.watchdog_s),
    diffScalar(READBACK_TOL, oldT.readback_tolerance, newT.readback_tolerance),
  ];
  return changes.filter((c): c is FieldChange => c !== null);
}

function targetChange(old: TargetPolicy | null, now: TargetPolicy | null): FieldChange {
  const added = old === null;
  const explanation = added ? "policy.diff.targetAdded" : "policy.diff.targetRemoved";
  return { field: "target", oldValue: old, newValue: now, loosening: added, explanation, params: {} };
}

function buildAddedTargetDiff(tag: string, draftT: TargetPolicy): TargetDiff {
  return { tag, status: "added", changes: [targetChange(null, draftT)], loosening: true };
}

function buildRemovedTargetDiff(tag: string, liveT: TargetPolicy): TargetDiff {
  return { tag, status: "removed", changes: [targetChange(liveT, null)], loosening: false };
}

function buildTargetDiff(tag: string, liveT?: TargetPolicy, draftT?: TargetPolicy): TargetDiff {
  if (!liveT && draftT) return buildAddedTargetDiff(tag, draftT);
  if (liveT && !draftT) return buildRemovedTargetDiff(tag, liveT);
  if (liveT && draftT) {
    const changes = compareTargetFields(liveT, draftT);
    return {
      tag,
      status: changes.length > 0 ? "modified" : "unchanged",
      changes,
      loosening: changes.some((c) => c.loosening),
    };
  }
  return { tag, status: "unchanged", changes: [], loosening: false };
}

function diffTargetDicts(
  liveTargets: Record<string, TargetPolicy>,
  draftTargets: Record<string, TargetPolicy>,
): TargetDiff[] {
  const allTags = Array.from(new Set([...Object.keys(liveTargets), ...Object.keys(draftTargets)])).sort();
  return allTags.map((tag) => buildTargetDiff(tag, liveTargets[tag], draftTargets[tag]));
}

function diffExtraProperties(
  liveDoc: PolicyDocument | null,
  draftDoc: PolicyDocument | null,
): FieldChange[] {
  const reserved = new Set(["version", "mode", "targets"]);
  const liveKeys = Object.keys(liveDoc ?? {}).filter((k) => !reserved.has(k));
  const draftKeys = Object.keys(draftDoc ?? {}).filter((k) => !reserved.has(k));
  const allKeys = Array.from(new Set([...liveKeys, ...draftKeys])).sort();
  const changes: FieldChange[] = [];
  for (const k of allKeys) {
    const oldVal = liveDoc ? liveDoc[k] : undefined;
    const newVal = draftDoc ? draftDoc[k] : undefined;
    if (stableStringify(oldVal) !== stableStringify(newVal)) {
      changes.push({ field: k, oldValue: oldVal, newValue: newVal, loosening: false, explanation: "policy.diff.neutral", params: {} });
    }
  }
  return changes;
}

/** Mode change between the documents; with no live policy the baseline is "off" (nothing is pinned). */
function diffDocumentMode(live: PolicyDocument | null, draft: PolicyDocument | null): FieldChange | null {
  if (!draft) return null;
  return diffMode(live ? live.mode : "off", draft.mode);
}

/**
 * Computes deep differences between live pinned policy and draft policy.
 */
export function diffPolicies(
  live: PolicyDocument | null,
  draft: PolicyDocument | null,
): PolicyDiff {
  if (!live && !draft) {
    return { modeChange: null, targetDiffs: [], extraFieldChanges: [], hasChanges: false, hasLoosening: false };
  }
  const modeChange = diffDocumentMode(live, draft);
  const liveTargets = live?.targets ?? {};
  const draftTargets = draft?.targets ?? {};
  const targetDiffs = diffTargetDicts(liveTargets, draftTargets);
  const extraFieldChanges = diffExtraProperties(live, draft);
  const modifiedTargets = targetDiffs.filter((t) => t.status !== "unchanged");
  const hasChanges = modeChange !== null || modifiedTargets.length > 0 || extraFieldChanges.length > 0;
  const hasLoosening = Boolean(modeChange?.loosening) || targetDiffs.some((t) => t.loosening);

  return { modeChange, targetDiffs, extraFieldChanges, hasChanges, hasLoosening };
}

function countDiffDirections(diff: PolicyDiff): { looseningCount: number; tighteningCount: number } {
  let loosening = diff.modeChange?.loosening ? 1 : 0;
  let tightening = diff.modeChange && !diff.modeChange.loosening ? 1 : 0;
  for (const t of diff.targetDiffs) {
    for (const c of t.changes) {
      if (c.loosening) loosening += 1;
      else tightening += 1;
    }
  }
  return { looseningCount: loosening, tighteningCount: tightening };
}

function computeRiskLevel(diff: PolicyDiff, looseningCount: number, addedTargets: number): "high" | "medium" | "low" | "none" {
  if (diff.hasLoosening || addedTargets > 0) {
    return diff.modeChange?.loosening || looseningCount > 2 ? "high" : "medium";
  }
  return diff.hasChanges ? "low" : "none";
}

/**
 * Produces an aggregated risk summary based on diff analysis.
 */
export function riskSummary(diff: PolicyDiff): RiskSummary {
  const { looseningCount, tighteningCount } = countDiffDirections(diff);
  const addedTargets = diff.targetDiffs.filter((t) => t.status === "added").length;
  const removedTargets = diff.targetDiffs.filter((t) => t.status === "removed").length;
  const modifiedTargets = diff.targetDiffs.filter((t) => t.status === "modified").length;
  const modeChanged = diff.modeChange !== null;
  const level = computeRiskLevel(diff, looseningCount, addedTargets);

  return { level, looseningCount, tighteningCount, addedTargets, removedTargets, modifiedTargets, modeChanged };
}

/** Number of invalid fields over all targets of a document (0 means it may be saved). */
export function countInvalidFields(doc: PolicyDocument): number {
  return Object.values(doc.targets).reduce((sum, target) => sum + Object.keys(validateTarget(target)).length, 0);
}

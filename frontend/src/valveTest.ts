// Pure logic of the valve stroke test screen: form parsing, the phase state machine
// and the translation of procedure steps and errors. No React and no fetch here, so
// every rule can be tested without a browser. The component wires these pieces together.
import type { ValvePlan, ValvePlanRequest, ValveAnalysis, ValveProcedureStep, ApiError } from "./api";
import { ApiError as ApiErrorClass } from "./api";
import type { Translate } from "./findings";
import { formatFixed } from "./format";

/** The five screens of the stroke test, in the order they are visited. */
export type Phase = "setup" | "checklist" | "plan" | "record" | "result";

/** Numeric phase order; a "back" is only allowed to a strictly smaller value. */
const PHASE_ORDER: Record<Phase, number> = {
  setup: 0,
  checklist: 1,
  plan: 2,
  record: 3,
  result: 4,
};

/** Form values as typed by the user; kept as strings so a half-typed number is not lost. */
export interface Settings {
  opStart: string;
  dwellS: string;
  opLow: string;
  opHigh: string;
  pvBand: string;
  stepSizes: string;
  stepsPerLeg: string;
}

/** The form values the screen opens with (a typical small-step test on a 0..100 % valve). */
export function defaultSettings(): Settings {
  return {
    opStart: "50",
    dwellS: "120",
    opLow: "0",
    opHigh: "100",
    pvBand: "",
    stepSizes: "1, 0.25",
    stepsPerLeg: "4, 12",
  };
}

/** Outcome of {@link parseSettings}: the request to send, or the first field that is wrong. */
export type ParseResult = { ok: true; request: ValvePlanRequest } | { ok: false; field: keyof Settings };

/**
 * Parse one form value as a finite number; a decimal comma is accepted ("1,5" is 1.5).
 * Returns null when the text is blank or not a number, so the caller reports the field.
 */
function parseNumber(text: string): number | null {
  const trimmed = text.trim().replace(",", ".");
  if (trimmed === "") {
    return null;
  }
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
}

/**
 * Parse a comma- or semicolon-separated list of positive numbers.
 * With a semicolon in the text only semicolons separate items, so decimal commas work
 * ("1; 0,5"); otherwise commas separate items ("1, 0.5").
 * A blank text returns an empty array (the field is optional); any bad item returns null.
 */
function parsePositiveList(text: string): number[] | null {
  const items = text
    .split(text.includes(";") ? ";" : ",")
    .map((item) => item.trim())
    .filter((item) => item !== "");
  if (items.length === 0) {
    return [];
  }
  const values: number[] = [];
  for (const item of items) {
    const value = parseNumber(item);
    if (value === null || value <= 0) {
      return null;
    }
    values.push(value);
  }
  return values;
}

/** Parse the steps-per-leg list: positive integers (at least 1). Null when any item is wrong. */
function parseIntegerList(text: string): number[] | null {
  const values = parsePositiveList(text);
  if (values === null) {
    return null;
  }
  return values.every((value) => Number.isInteger(value) && value >= 1) ? values : null;
}

/**
 * Build the plan request from the form values.
 * @returns `{ok: true, request}` when the form is valid, otherwise the first invalid field
 *   in the order opStart, dwellS, opLow, opHigh, pvBand, stepSizes, stepsPerLeg.
 */
export function parseSettings(settings: Settings): ParseResult {
  const opStart = parseNumber(settings.opStart);
  if (opStart === null) {
    return { ok: false, field: "opStart" };
  }
  const dwellS = parseNumber(settings.dwellS);
  if (dwellS === null || !Number.isInteger(dwellS) || dwellS <= 0) {
    return { ok: false, field: "dwellS" };
  }
  const opLow = parseNumber(settings.opLow);
  if (opLow === null) {
    return { ok: false, field: "opLow" };
  }
  const opHigh = parseNumber(settings.opHigh);
  if (opHigh === null) {
    return { ok: false, field: "opHigh" };
  }
  const pvBandText = settings.pvBand.trim();
  const pvBand = pvBandText === "" ? null : parseNumber(pvBandText);
  if (pvBandText !== "" && (pvBand === null || pvBand <= 0)) {
    return { ok: false, field: "pvBand" };
  }
  const stepSizes = parsePositiveList(settings.stepSizes);
  if (stepSizes === null) {
    return { ok: false, field: "stepSizes" };
  }
  const stepsPerLeg = parseIntegerList(settings.stepsPerLeg);
  if (stepsPerLeg === null) {
    return { ok: false, field: "stepsPerLeg" };
  }
  return { ok: true, request: buildRequest({ opStart, dwellS, opLow, opHigh, pvBand, stepSizes, stepsPerLeg }) };
}

/** Parsed, validated form values that become a plan request. */
interface RequestOptions {
  opStart: number;
  dwellS: number;
  opLow: number;
  opHigh: number;
  pvBand: number | null;
  stepSizes: number[];
  stepsPerLeg: number[];
}

/** Fill the request; blank optional lists stay omitted so the server keeps its own default. */
function buildRequest(options: RequestOptions): ValvePlanRequest {
  const { opStart, dwellS, opLow, opHigh, pvBand, stepSizes, stepsPerLeg } = options;
  const request: ValvePlanRequest = { op_start: opStart, dwell_s: dwellS, op_low: opLow, op_high: opHigh };
  if (pvBand !== null) {
    request.pv_band = pvBand;
  }
  if (stepSizes.length > 0) {
    request.step_sizes = stepSizes;
  }
  if (stepsPerLeg.length > 0) {
    request.steps_per_leg = stepsPerLeg;
  }
  return request;
}

/** One error shown to the user; `code`/`field` are stable server codes, message is free text. */
export interface ValveError {
  code: string | null;
  field: string | null;
  message: string;
}

/** Everything the valve screen keeps between renders. */
export interface ValveState {
  phase: Phase;
  settings: Settings;
  /** Checklist answers, always length 3 so the component can index them. */
  checks: [boolean, boolean, boolean];
  plan: ValvePlan | null;
  analysis: ValveAnalysis | null;
  error: ValveError | null;
  busy: boolean;
}

/** The starting state: defaults on the setup screen, nothing planned, no request in flight. */
export function initialState(): ValveState {
  return {
    phase: "setup",
    settings: defaultSettings(),
    checks: [false, false, false],
    plan: null,
    analysis: null,
    error: null,
    busy: false,
  };
}

/** Every user interaction the valve screen handles; the reducer is the only place state changes. */
export type ValveAction =
  | { type: "editSetting"; key: keyof Settings; value: string }
  | { type: "planRequested" }
  | { type: "planReady"; plan: ValvePlan }
  | { type: "toggleCheck"; index: 0 | 1 | 2 }
  | { type: "acceptChecklist" }
  | { type: "showRecord" }
  | { type: "analysisRequested" }
  | { type: "analysed"; analysis: ValveAnalysis }
  | { type: "failed"; error: ValveError }
  | { type: "backTo"; phase: Phase }
  | { type: "reset" };

/** All three checklist boxes are ticked. */
function allChecked(checks: ValveState["checks"]): boolean {
  return checks.every((checked) => checked);
}

/** True when `target` comes before `current`, so a "back" is allowed. */
function isEarlierPhase(target: Phase, current: Phase): boolean {
  return PHASE_ORDER[target] < PHASE_ORDER[current];
}

/** Go back to `phase`, dropping every decision made after it. */
function goBack(state: ValveState, phase: Phase): ValveState {
  if (phase === "setup") {
    return { ...state, phase, plan: null, checks: [false, false, false], analysis: null, error: null };
  }
  if (phase === "checklist") {
    return { ...state, phase, checks: [false, false, false], error: null };
  }
  return { ...state, phase, error: null };
}

/**
 * Reduce one action into the next state.
 * An edited setting invalidates any existing plan, so the user sees fresh validation.
 */
export function valveReducer(state: ValveState, action: ValveAction): ValveState {
  switch (action.type) {
    case "editSetting": {
      const settings = { ...state.settings, [action.key]: action.value };
      const hadPlan = state.plan !== null;
      return {
        ...state,
        settings,
        error: null,
        plan: hadPlan ? null : state.plan,
        checks: hadPlan ? [false, false, false] : state.checks,
        phase: hadPlan ? "setup" : state.phase,
      };
    }
    case "planRequested":
      return { ...state, busy: true, error: null };
    case "planReady":
      return { ...state, busy: false, error: null, plan: action.plan, phase: "checklist", checks: [false, false, false] };
    case "toggleCheck": {
      const checks = [...state.checks] as ValveState["checks"];
      checks[action.index] = !checks[action.index];
      return { ...state, checks };
    }
    case "acceptChecklist":
      return allChecked(state.checks) ? { ...state, phase: "plan" } : state;
    case "showRecord":
      return state.phase === "plan" ? { ...state, phase: "record" } : state;
    case "analysisRequested":
      return { ...state, busy: true, error: null };
    case "analysed":
      return { ...state, busy: false, error: null, analysis: action.analysis, phase: "result" };
    case "failed":
      return { ...state, busy: false, error: action.error };
    case "backTo":
      return isEarlierPhase(action.phase, state.phase) ? goBack(state, action.phase) : state;
    case "reset":
      return { ...initialState(), settings: state.settings };
  }
}

/**
 * Turn one server procedure step into a sentence in the UI language.
 * Parameters are already-formatted strings; the translator only picks the template.
 */
export function procedureSentence(t: Translate, step: ValveProcedureStep): string {
  const op = formatFixed(step.params.op ?? 0, 2);
  const opStart = formatFixed(step.params.op_start ?? 0, 2);
  if (step.code === "abort") {
    const band = step.params.pv_band;
    if (band !== null && band !== undefined) {
      return t("valve.plan.step.abortBand", { band: formatFixed(band, 2), op: opStart });
    }
    return t("valve.plan.step.abort", { op: opStart });
  }
  if (step.code === "set_start" || step.code === "step") {
    return t(`valve.plan.step.${step.code}`, { op, dwell: String(step.params.dwell_s ?? "") });
  }
  if (step.code === "return_auto") {
    return t("valve.plan.step.return_auto", { op });
  }
  return t(`valve.plan.step.${step.code}`);
}

/**
 * Turn a thrown value into a human sentence.
 * ApiErrors carry a stable code (translated); anything else is likely a network failure.
 */
export function valveErrorMessage(t: Translate, error: unknown): string {
  if (error instanceof ApiErrorClass) {
    const apiError = error as ApiError;
    if (apiError.code !== null) {
      return t(`valve.error.code.${apiError.code}`, { message: apiError.message });
    }
    return t("valve.error.other", { message: apiError.message });
  }
  return t("valve.error.network");
}

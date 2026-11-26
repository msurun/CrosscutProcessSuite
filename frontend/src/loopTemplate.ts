// frontend/src/loopTemplate.ts
/**
 * Typed client and pure helpers for loop templates (PRODUCT 4.1).
 *
 * A template is the generic knowledge of one loop type: expected dynamics, KPI limits,
 * diagnosis rules, tuning rule and target, allowed tests and a safe default step. The API
 * serves the packaged library plus any site copy saved under the data root.
 */

import { apiFetch } from "./http";

const API_PREFIX = "/api/loop-templates";

export type ProcessKind = "self_regulating" | "integrating";
export type DiagnosisRule = "instrument" | "valve" | "external" | "design_or_mode" | "tuning";
export type TuningRule = "simc" | "amigo" | "lambda";
export type TestType = "step" | "stroke" | "bump";
export type TemplateOrigin = "builtin" | "site";

export const PROCESS_KINDS: readonly ProcessKind[] = ["self_regulating", "integrating"];
export const DIAGNOSIS_RULES: readonly DiagnosisRule[] = [
  "instrument",
  "valve",
  "external",
  "design_or_mode",
  "tuning",
];
export const TUNING_RULES: readonly TuningRule[] = ["simc", "amigo", "lambda"];
export const TEST_TYPES: readonly TestType[] = ["step", "stroke", "bump"];

/** Expected identified dynamics; gain is a magnitude and all times are seconds. */
export interface LoopDynamics {
  gain_min: number;
  gain_max: number;
  time_constant_s_min: number;
  time_constant_s_max: number;
  dead_time_s_min: number;
  dead_time_s_max: number;
}

/** KPI limits; shares are fractions from 0 to 1. */
export interface LoopKpiThresholds {
  service_factor_min: number;
  saturation_share_max: number;
  oscillation_index_max: number;
  noise_ratio_max: number;
}

export interface LoopTuning {
  rule: TuningRule;
  target_closed_loop_time_constant_ratio: number;
  robustness?: number;
}

export interface LoopTests {
  allowed: TestType[];
  default_step_pct: number;
}

/** One loop type as stored; `origin` says whether the site overrides the packaged file. */
export interface LoopTemplate {
  key: string;
  label: string;
  description?: string;
  process_kind: ProcessKind;
  dynamics: LoopDynamics;
  kpi_thresholds: LoopKpiThresholds;
  diagnosis_rules: DiagnosisRule[];
  tuning: LoopTuning;
  tests: LoopTests;
  origin?: TemplateOrigin;
}

/** An HTTP failure; `problems` holds the server's detail as one or more readable lines. */
export class LoopTemplateApiError extends Error {
  readonly status: number;
  readonly problems: string[];

  constructor(status: number, problems: string[]) {
    super(problems.join("; ") || String(status));
    this.name = "LoopTemplateApiError";
    this.status = status;
    this.problems = problems;
  }
}

/** The lines of a FastAPI `detail`: a string, a list of strings or a list of {msg} objects. */
function linesOf(detail: unknown): string[] {
  if (typeof detail === "string") return [detail];
  if (!Array.isArray(detail)) return [];
  return detail.map((one) =>
    typeof one === "string" ? one : String((one as { msg?: unknown }).msg ?? ""),
  );
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(url, init);
  if (!response.ok) {
    let detail: unknown = null;
    try {
      detail = ((await response.json()) as { detail?: unknown } | null)?.detail;
    } catch {
      detail = null;
    }
    const lines = linesOf(detail);
    throw new LoopTemplateApiError(response.status, lines.length > 0 ? lines : [response.statusText]);
  }
  return (await response.json()) as T;
}

/** GET /loop-templates: the built-in library with site copies already merged in. */
export async function listLoopTemplates(): Promise<LoopTemplate[]> {
  const body = await requestJson<{ templates: LoopTemplate[] }>(API_PREFIX);
  return body.templates;
}

/** GET /loop-templates/{key}. */
export async function getLoopTemplate(key: string): Promise<LoopTemplate> {
  return requestJson<LoopTemplate>(`${API_PREFIX}/${encodeURIComponent(key)}`);
}

/** The body the API accepts: everything except the read-only `origin` field. */
export function templateBody(template: LoopTemplate): Omit<LoopTemplate, "origin"> {
  const copy = { ...template };
  delete copy.origin;
  return copy;
}

/** PUT /loop-templates/{key}: save a site copy and return it with origin "site". */
export async function saveLoopTemplate(key: string, template: LoopTemplate): Promise<LoopTemplate> {
  const body = JSON.stringify(templateBody(template));
  return requestJson<LoopTemplate>(`${API_PREFIX}/${encodeURIComponent(key)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body,
  });
}

/** One line for the template list: gain, time constant and dead time with units. */
export function formatDynamics(template: LoopTemplate): string {
  const dynamics = template.dynamics;
  return (
    `K ${dynamics.gain_min}–${dynamics.gain_max}, ` +
    `T ${dynamics.time_constant_s_min}–${dynamics.time_constant_s_max} s, ` +
    `L ${dynamics.dead_time_s_min}–${dynamics.dead_time_s_max} s`
  );
}

/** One line for the template list: tuning rule and closed-loop target. */
export function formatTuning(template: LoopTemplate): string {
  const ratio = template.tuning.target_closed_loop_time_constant_ratio;
  return `${template.tuning.rule.toUpperCase()}, τcl/L ${ratio}`;
}

/** Return a copy of `values` with `value` added, or removed when it was already there. */
export function toggleValue<T>(values: readonly T[], value: T): T[] {
  return values.includes(value) ? values.filter((one) => one !== value) : [...values, value];
}

/** Field keys the editor marks invalid when a bound is impossible. */
export function invalidRangeFields(template: LoopTemplate): string[] {
  const problems: string[] = [];
  const dynamics = template.dynamics;
  if (dynamics.gain_min < 0 || dynamics.gain_max <= dynamics.gain_min) {
    problems.push("dynamics.gain");
  }
  if (dynamics.time_constant_s_min <= 0 || dynamics.time_constant_s_max <= dynamics.time_constant_s_min) {
    problems.push("dynamics.timeConstant");
  }
  if (dynamics.dead_time_s_min < 0 || dynamics.dead_time_s_max <= dynamics.dead_time_s_min) {
    problems.push("dynamics.deadTime");
  }
  const kpi = template.kpi_thresholds;
  if (kpi.service_factor_min < 0 || kpi.service_factor_min > 1) problems.push("kpi.serviceFactor");
  if (kpi.saturation_share_max < 0 || kpi.saturation_share_max > 1) problems.push("kpi.saturation");
  if (kpi.oscillation_index_max < 0 || kpi.oscillation_index_max > 1) problems.push("kpi.oscillation");
  if (kpi.noise_ratio_max < 0) problems.push("kpi.noise");
  if (template.tuning.target_closed_loop_time_constant_ratio <= 0) problems.push("tuning.target");
  if (template.tests.default_step_pct <= 0 || template.tests.default_step_pct > 100) {
    problems.push("tests.defaultStep");
  }
  return problems;
}

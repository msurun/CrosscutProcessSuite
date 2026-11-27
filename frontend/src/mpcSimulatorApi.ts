// Typed read-only client for comparing MPC and current PID on an identified model.
// Simulation requests never create artifacts, gateway proposals or controller commands.
import { apiFetch } from "./http";

export type ScenarioKind = "sp_step" | "dv_step" | "constraint_active";
export const LIMIT_FIELDS = ["mv_lower", "mv_upper", "cv_lower", "cv_upper", "priorities",
  "move_max", "rate_max", "target_rate", "funnel_start", "funnel_end"] as const;
export type SimulationLimits = Record<(typeof LIMIT_FIELDS)[number], number[]>;
export interface SimulationRequest {
  artifact_id: string;
  controller_id: string;
  pid_tunings: PidSnapshot[];
  limits: SimulationLimits;
  settings: { prediction_horizon: number; move_horizon: number; move_suppression: number };
  scenario: { kind: ScenarioKind; steps: number; step_at: number; amplitude: number; cv_index: number; dv_index: number };
}
export interface PidSnapshot { loop_id: string; kp: number; ti_s: number; td_s: number; cv_index: number }
export interface SimulationTrace {
  cvs: number[][];
  mvs: number[][];
  kpis: {
    iae: number[]; overshoot: number[]; settling_time_s: (number | null)[]; mv_travel: number[];
    constraint_violations: Record<string, number[]>;
  };
}
export interface SimulationResult {
  cv_names?: string[];
  mv_names?: string[];
  time_s: number[];
  targets: number[][];
  disturbances: number[][];
  mpc: SimulationTrace;
  pid: SimulationTrace;
  limits: Pick<SimulationLimits, "mv_lower" | "mv_upper" | "cv_lower" | "cv_upper">;
}

/** Run a deterministic preview; show the server's validation or permission refusal. */
export async function simulateMpc(body: SimulationRequest): Promise<SimulationResult> {
  const response = await apiFetch("/api/mpc/simulate", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : JSON.stringify(result.detail));
  return result as SimulationResult;
}

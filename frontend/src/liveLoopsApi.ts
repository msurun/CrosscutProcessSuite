// Client for the live loop worklist: the catalogue loops the runtime analyses and their KPI history.
// Reuses getJson/API_PREFIX from api.ts so errors look like every other call.
import { API_PREFIX, getJson, sendJson } from "./api";

/** The latest KPI dict of a loop (keys of the runtime `kpi_from_series`); every key may be missing or null. */
export type LiveKpi = Record<string, unknown>;

/** What the user decided about a finding (issue #150). */
export type FindingOutcome = "fixed" | "not_a_problem" | "deferred" | "maintenance_raised";

/** Who recorded an outcome, when, and its optional deferral date or work order. */
export interface FindingOutcomeDetail {
  until_utc: string | null;
  work_order: string | null;
  actor: string;
  at_utc: string;
}

/** A finding the runtime observed: a stable code and when it first appeared (null when unknown). */
export interface LiveFinding {
  code: string;
  since_utc: string | null;
  outcome?: FindingOutcome;
  outcome_detail?: FindingOutcomeDetail;
}

/** The fields of one outcome the user saves; `until_utc` only for deferred. */
export interface FindingOutcomeInput {
  outcome: FindingOutcome;
  until_utc?: string;
  work_order?: string;
}

/** One catalogue loop of `GET /api/live/loops`; `job` is null when no loop_kpi job covers it. */
export interface LiveLoop {
  id: string;
  name: string;
  type: string | null;
  job: string | null;
  job_status: string | null;
  last_run_utc: string | null;
  fresh: boolean;
  kpi: LiveKpi | null;
  findings: LiveFinding[];
  /** Operating mode of the newest sample (#146); null when the catalogue defines no modes. */
  mode?: string | null;
  /** "mode": the headline KPI is the current mode's; "all_running": that mode had too few samples. */
  kpi_scope?: "mode" | "all_running" | null;
  /** KPI of every operating mode with enough samples, stopped samples left out. */
  by_mode?: Record<string, LiveKpi>;
}

/** One stored observation of a loop's KPI. */
export interface LiveObservation {
  utc: string;
  kpi: LiveKpi;
  mode?: string | null;
}

/** A loop row plus its KPI history (`GET /api/live/loops/{id}`). */
export interface LiveLoopDetail extends LiveLoop {
  history: LiveObservation[];
}

/** Fetches the live loop worklist. */
export async function fetchLiveLoops(): Promise<LiveLoop[]> {
  const body = await getJson<{ loops: LiveLoop[] }>(`${API_PREFIX}/live/loops`);
  return body.loops;
}

/** Fetches one loop with its newest `limit` observations. */
export function fetchLiveLoop(id: string, limit = 200): Promise<LiveLoopDetail> {
  return getJson<LiveLoopDetail>(`${API_PREFIX}/live/loops/${encodeURIComponent(id)}?limit=${limit}`);
}

/** Saves the user's outcome for one finding occurrence (loop + code + first-seen time). */
export function setFindingOutcome(
  loopId: string, finding: LiveFinding, input: FindingOutcomeInput,
): Promise<FindingOutcomeDetail> {
  const path = `${API_PREFIX}/live/loops/${encodeURIComponent(loopId)}/findings/${encodeURIComponent(finding.code)}/outcome`;
  return sendJson<FindingOutcomeDetail>("PUT", path, { since_utc: finding.since_utc, ...input });
}

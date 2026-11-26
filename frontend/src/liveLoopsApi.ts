// Client for the live loop worklist: the catalogue loops the runtime analyses and their KPI history.
// Reuses getJson/API_PREFIX from api.ts so errors look like every other call.
import { API_PREFIX, getJson } from "./api";

/** The latest KPI dict of a loop (keys of the runtime `kpi_from_series`); every key may be missing or null. */
export type LiveKpi = Record<string, unknown>;

/** A finding the runtime observed: a stable code and when it first appeared (null when unknown). */
export interface LiveFinding {
  code: string;
  since_utc: string | null;
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
}

/** One stored observation of a loop's KPI. */
export interface LiveObservation {
  utc: string;
  kpi: LiveKpi;
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

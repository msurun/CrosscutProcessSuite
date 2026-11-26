// Read-only summaries for the console start page.
// Keep selection separate from requests so unavailable services remain independent.
import type { LiveLoop } from "./liveLoopsApi";
import type { EquipmentAnomaly } from "./equipmentAnomalyApi";

/** Maximum number of findings shown before opening the full worklist. */
export const OVERVIEW_FINDING_LIMIT = 5;

/** Result of one independent read; failure never means an empty successful response. */
export type OverviewSource<Value> =
  | { status: "loading" }
  | { status: "unavailable" }
  | { status: "ready"; value: Value };

/** Select findings in the server's worklist order without changing that order. */
export function topLoopFindings(loops: readonly LiveLoop[]): LiveLoop[] {
  return loops.filter((loop) => loop.findings.length > 0).slice(0, OVERVIEW_FINDING_LIMIT);
}

/** Closed historical events are evidence, rather than current anomaly findings. */
export function activeAnomalies(equipment: readonly EquipmentAnomaly[]): EquipmentAnomaly[] {
  return equipment.filter((row) => row.open_event !== null || row.live_state.status === "anomaly");
}

/** Shelving suppresses equipment alarms while retaining their anomaly evidence. */
export function activeEquipmentAlarms(
  equipment: readonly EquipmentAnomaly[], nowMilliseconds: number = Date.now(),
): EquipmentAnomaly[] {
  return activeAnomalies(equipment).filter((row) => !row.live_state.shelved &&
    (row.shelved_until_utc === null || Date.parse(row.shelved_until_utc) <= nowMilliseconds));
}

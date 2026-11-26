// Typed client for catalogue equipment learning and live anomaly events.
// Shared request helpers retain authentication, CSRF protection and API errors.
import { API_PREFIX, getJson, sendJson } from "./api";

/** Persisted training states; none means that no model has been saved. */
export type EquipmentModelStatus = "none" | "learned" | "learning" | "not_enough_data";
/** Operator feedback accepted by the audited outcome endpoint. */
export type EquipmentOutcome = "real" | "false_alarm" | "maintenance_raised" | "deferred";
/** Closed interval in elapsed seconds from the first dataset sample. */
export type EquipmentWindow = [number, number];
/** Aware UTC timestamps excluded from training, including both endpoints. */
export type EquipmentExclusion = [string, string];

/** Saved learning evidence returned for each catalogue equipment item. */
export interface EquipmentModelSummary {
  equipment_id: string;
  status: EquipmentModelStatus;
  windows: EquipmentWindow[];
  variables: string[];
}

/** Full persisted learning result; coefficient documents remain backend-owned. */
export interface EquipmentLearnedModel {
  status: EquipmentModelStatus;
  dataset_id: string;
  windows: EquipmentWindow[];
  variables: string[];
  reasons: Record<string, number>;
  pca: Record<string, unknown> | null;
  fallback: "per_loop" | null;
  per_loop: Record<string, Record<string, unknown>>;
  regressions: Record<string, Record<string, unknown>>;
  previous: number[] | null;
  ewma: Record<string, number>;
}

/** Ranked dimensionless contribution share for one measurement tag. */
export interface EquipmentContribution {
  tag: string;
  share: number;
}

/** Conditional residual in training standard deviations, with EWMA sign. */
export interface EquipmentResidual {
  tag: string;
  z: number;
  trend: number;
}

/** Latest snapshot of one event, identified by equipment and opening timestamp. */
export interface EquipmentEvent {
  equipment: string;
  opened_utc: string;
  closed_utc: string | null;
  peak: number;
  contributions: EquipmentContribution[];
  residuals: EquipmentResidual[];
  loops_affected: string[];
  outcome?: EquipmentOutcome | null;
}

/** Most recent runtime observation; missing statistics have not been scored. */
export interface EquipmentLiveState {
  status: "unknown" | "no_model" | "stopped" | "anomaly" | "ok";
  open_event?: EquipmentEvent | null;
  reason?: string;
  shelved?: boolean;
  t2?: number | null;
  spe?: number | null;
  ewma?: Record<string, number>;
}

/** Worklist row joined from model, runtime state and newest fifty event identities. */
export interface EquipmentAnomaly {
  equipment_id: string;
  model_status: EquipmentModelStatus;
  live_state: EquipmentLiveState;
  open_event: EquipmentEvent | null;
  events: EquipmentEvent[];
  shelved_until_utc: string | null;
}

/** Effective shelving expiry returned after an operator action. */
export interface EquipmentShelf {
  equipment_id: string;
  until_utc: string | null;
}

/** List training status and accepted windows for every equipment item. */
export function fetchEquipmentModels(): Promise<EquipmentModelSummary[]> {
  return getJson<EquipmentModelSummary[]>(`${API_PREFIX}/equipment/models`);
}

/** List live equipment anomalies together with their recent event history. */
export function fetchEquipmentAnomalies(): Promise<EquipmentAnomaly[]> {
  return getJson<EquipmentAnomaly[]>(`${API_PREFIX}/equipment/anomalies`);
}

/** Learn from backend-proposed usable windows, optionally excluding UTC spans. */
export function learnEquipment(
  datasetId: string, equipmentId: string, exclusions: EquipmentExclusion[] = [],
): Promise<EquipmentLearnedModel> {
  const dataset = encodeURIComponent(datasetId);
  const equipment = encodeURIComponent(equipmentId);
  return sendJson<EquipmentLearnedModel>("POST",
    `${API_PREFIX}/datasets/${dataset}/equipment/${equipment}/learn`, { exclusions });
}

/** Suppress this equipment's alarms until an explicit future UTC instant. */
export function shelveEquipment(equipmentId: string, untilUtc: string): Promise<EquipmentShelf> {
  return sendJson<EquipmentShelf>("POST",
    `${API_PREFIX}/equipment/${encodeURIComponent(equipmentId)}/shelve`, { until_utc: untilUtc });
}

/** Remove this equipment's shelving expiry. */
export function unshelveEquipment(equipmentId: string): Promise<EquipmentShelf> {
  return sendJson<EquipmentShelf>("DELETE",
    `${API_PREFIX}/equipment/${encodeURIComponent(equipmentId)}/shelve`, undefined);
}

/** Save feedback for the exact equipment event identity. */
export function setEquipmentOutcome(
  openedUtc: string, equipmentId: string, outcome: EquipmentOutcome,
): Promise<EquipmentEvent> {
  const event = encodeURIComponent(openedUtc);
  const equipment = encodeURIComponent(equipmentId);
  return sendJson<EquipmentEvent>("PUT",
    `${API_PREFIX}/equipment/events/${event}/${equipment}/outcome`, { outcome });
}

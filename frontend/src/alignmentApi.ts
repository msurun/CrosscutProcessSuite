// Alignment scans compare user laboratory results with a dataset signal.
// Delays and their uncertainty limits use seconds throughout the HTTP interface.
import { sendJson } from "./api";

/** Candidate delay range and the online analyser or process tag to compare. */
export interface AlignmentRequest {
  reference_tag: string;
  min_delay_s: number;
  max_delay_s: number;
  step_s: number;
}

/** Correlation profile and the estimated interval of the physical delay. */
export interface AlignmentResult {
  best_delay_s: number;
  interval_low_s: number;
  interval_high_s: number;
  method: string;
  profile: { delay_s: number; correlation: number | null }[];
}

/** Scan delays without changing the stored sensor configuration. */
export function scanAlignment(datasetId: string, sensorId: string, request: AlignmentRequest): Promise<AlignmentResult> {
  const dataset = encodeURIComponent(datasetId);
  const sensor = encodeURIComponent(sensorId);
  return sendJson<AlignmentResult>("POST", `/api/datasets/${dataset}/softsensor/${sensor}/alignment-scan`, request);
}

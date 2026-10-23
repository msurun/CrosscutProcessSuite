// Pure helpers of the Soft sensor page: the train-end check in hours, the client-side check of a lab
// CSV, the mapping of API errors to message codes and the order/explanation of the validity classes.
// No React, so they are unit-tested alone. All times from the API are seconds from the record start.
import { ApiError, type SoftSensorValidity } from "./api";
import { parseHours } from "./anomaly";

const SECONDS_PER_HOUR = 3600;
/** Share of the record used for training by default. */
const DEFAULT_TRAIN_SHARE = 0.75;
const HALF_HOUR_STEPS = 2;
/** Schema defaults, used when the stored config leaves a field out. */
export const DEFAULT_LAGS_S: readonly number[] = [0, 300, 900, 1800];
export const DEFAULT_LAB_DELAY_S = 3600;
export const DEFAULT_SAMPLE_PERIOD_S = 60;
const BYTE_ORDER_MARK = /^﻿/;

/** The validity classes in the order they are listed (usable first, the worst last). */
export const VALIDITY_ORDER: readonly SoftSensorValidity[] = ["ok", "missing_input", "out_of_range", "extrapolation"];

/** Classes whose estimates must not be used. */
export const UNRELIABLE: readonly SoftSensorValidity[] = ["out_of_range", "extrapolation"];

/** Why a train end typed in hours is not acceptable (the string is the `soft.fit.<code>` key part). */
export type TrainEndError = "notNumber" | "notPositive" | "beyond";

/** A checked train end: seconds on success, otherwise the problem. */
export type TrainEndCheck = { ok: true; endS: number } | { ok: false; error: TrainEndError };

/** Default train end in hours: three quarters of the record in steps of 0.5 h (at least 0.5 h). */
export function defaultTrainEndHours(recordHours: number | null): number {
  if (recordHours === null || !(recordHours > 0)) return 1;
  return Math.max(0.5, Math.floor(recordHours * DEFAULT_TRAIN_SHARE * HALF_HOUR_STEPS) / HALF_HOUR_STEPS);
}

/** Checks the train end (hours from the record start) against the record length (hours, or null if unknown). */
export function validateTrainEnd(text: string, recordHours: number | null): TrainEndCheck {
  const hours = parseHours(text);
  if (hours === null) return { ok: false, error: "notNumber" };
  if (hours <= 0) return { ok: false, error: "notPositive" };
  if (recordHours !== null && hours > recordHours) return { ok: false, error: "beyond" };
  return { ok: true, endS: hours * SECONDS_PER_HOUR };
}

/** What the API error means for the user, when it is one of the known cases. */
export type SoftErrorCode = "notFitted" | "stale" | "unknownTag" | "noLab" | "labCsv" | "fitData";

/** Classifies an API error by status and message (the API sends no machine codes for these); null if unknown. */
export function softErrorCode(error: unknown): SoftErrorCode | null {
  if (!(error instanceof ApiError)) return null;
  const message = error.message.toLowerCase();
  if (error.status === 404 && message.includes("model not fitted")) return "notFitted";
  if (error.status === 404 && message.includes("no lab results")) return "noLab";
  if (error.status === 422 && message.includes("model is stale")) return "stale";
  if (message.includes("unknown tags")) return "unknownTag";
  if (error.status === 422 && /^(csv_text|origin_iso|line \d+)/.test(message)) return "labCsv";
  if (error.status === 422 && /too few valid rows|constant column|no pls component|train_end_s/.test(message)) return "fitData";
  return null;
}

/** Problem found in lab CSV text before it is sent (the API checks it again and names the line). */
export type LabTextError = "empty" | "columns";

/** Checks that the text is not empty and that its header has the columns sample_time and value. */
export function checkLabText(text: string): LabTextError | null {
  const first = text.split(/\r?\n/).find((line) => line.trim() !== "");
  if (first === undefined) return "empty";
  const header = first.replace(BYTE_ORDER_MARK, "").split(/[;\t,]/).map((cell) => cell.trim().toLowerCase());
  return header.includes("sample_time") && header.includes("value") ? null : "columns";
}

/** First eight characters of a hash, for display. */
export function shortHash(hash: string): string {
  return hash.slice(0, 8);
}

/** Share of `count` in `total` as a percentage (0 when the total is 0). */
export function percentOf(count: number, total: number): number {
  return total > 0 ? (count / total) * 100 : 0;
}

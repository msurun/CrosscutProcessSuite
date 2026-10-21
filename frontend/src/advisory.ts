// Pure helpers of the Advisory page: the acknowledgement state of each advice, ack form
// validation, the reason codes and number/time formatting. No React, so they are unit-tested alone.
// Wording rule (ADR 010): the firing strength is called "activation", never confidence.
import type { AckDecision, AckRecord, AdviceRecord, AdvisoryLogRecord, GateState } from "./api";

/** Reason codes offered in the acknowledgement form; the labels are the `advisory.reason.<code>` strings. */
export const REASON_CODES = [
  "agrees_with_process",
  "disagrees_with_process",
  "equipment_limit",
  "already_handled",
  "need_more_data",
  "other",
] as const;

/** The decisions in the order the buttons are shown. */
export const DECISIONS: readonly AckDecision[] = ["accepted", "rejected", "deferred"];

/** Marker drawn before the direction word; the word always follows, so colour and shape are never alone. */
export const DIRECTION_ICON = { increase: "▲", decrease: "▼", hold: "■" } as const;

/** What the operator typed into the acknowledgement form. */
export interface AckDraft {
  reasonCode: string;
  who: string;
  note: string;
}

/** Which required fields of an acknowledgement are missing. */
export interface AckErrors {
  who: boolean;
  reasonCode: boolean;
}

/** Both `who` and the reason code are required; a blank (spaces only) `who` counts as missing. */
export function validateAck(draft: AckDraft): AckErrors {
  return { who: draft.who.trim() === "", reasonCode: draft.reasonCode.trim() === "" };
}

/** True when no required field is missing. */
export function ackIsValid(errors: AckErrors): boolean {
  return !errors.who && !errors.reasonCode;
}

/** The newest acknowledgement of each advice, by advice id (a later ack replaces an earlier one). */
export function latestAcks(records: readonly AdvisoryLogRecord[]): Map<string, AckRecord> {
  const acks = new Map<string, AckRecord>();
  for (const record of records) {
    if (record.kind === "ack") acks.set(record.advice_id, record);
  }
  return acks;
}

/**
 * The advice records of a log, newest first. An advice id is a hash of config, rule base and time,
 * so replaying the same stretch twice logs the same id again; only its first record is kept.
 */
export function advicesNewestFirst(records: readonly AdvisoryLogRecord[]): AdviceRecord[] {
  const seen = new Set<string>();
  const advices: AdviceRecord[] = [];
  for (const record of records) {
    if (record.kind !== "advice" || seen.has(record.advice_id)) continue;
    seen.add(record.advice_id);
    advices.push(record);
  }
  return advices.reverse();
}

/** CSS modifier of the status chip that shows a gate state. */
export function gateChipClass(state: GateState): string {
  const modifier = { open: "ok", degraded: "warning", blocked: "problem" }[state];
  return `status-chip status-chip--${modifier}`;
}

/** UTC time of a nanosecond timestamp as `YYYY-MM-DD HH:MM:SS UTC` (the same in every locale). */
export function formatAdviceTime(tNs: number): string {
  return `${new Date(tNs / 1e6).toISOString().slice(0, 19).replace("T", " ")} UTC`;
}

/** A unit-less number with at most 2 decimals; `null` or `undefined` gives an empty string. */
export function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(Math.round(value * 100) / 100);
}

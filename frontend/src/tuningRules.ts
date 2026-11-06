// frontend/src/tuningRules.ts
/**
 * Pure rules of the tuning proposals view: status groups and chips, who may approve, expiry
 * countdown, and the mapping of API failures to locale keys. No DOM, no network. The server
 * re-checks everything; these rules only explain disabled controls and refusals.
 */

import type { CanResult } from "./AuthContext";
import type { Translate } from "./findings";
import { sameActor } from "./policyModel";
import { TuningApiError, type TuningProposal } from "./tuningApi";

/** Status groups offered by the filter (the part of a status before a colon). */
export const STATUS_GROUPS = [
  "draft", "queued", "applied", "reviewing", "reviewed", "rejected", "expired", "refused",
] as const;

export type StatusLevel = "ok" | "warning" | "problem" | "unused";

const WHY_PREFIX = "tuning.proposals.why.";
const MS_PER_S = 1000;
const S_PER_MIN = 60;
const S_PER_H = 3600;

/** Machine codes the server (API, loops, gateway) may answer; each has a tuning.err.<code> text. */
export const KNOWN_CODES: readonly string[] = [
  "from_mismatch", "out_of_limits", "ratio_exceeded", "loop_busy", "expired", "id_conflict",
  "service_cannot_propose_tuning", "proposer_required", "self_approval", "author_equals_approver",
  "min_interval", "mode_off", "killed", "no_param_plant", "duplicate_target", "loop_mismatch",
  "clock_not_started", "expiry_too_long", "bad_time", "advisory_only", "dry_run",
  "not_confirm_mode", "partial_revert", "revert_failed", "comm_loss", "mode_unsupported",
  "unknown_proposal", "unknown_loop", "no_kpi_job", "no_live_values", "no_param_targets",
  "not_queued", "not_applied", "not_open", "no_gateway_key", "proposal_busy", "forbidden",
  "transition_refused", "blocked", "no_settings", "unsupported_method", "missing_range",
  "missing_target", "missing_current", "no_op", "preview_unstable", "no_model",
  "invalid_preview", "missing_read", "unknown_vendor_form", "integrating_not_supported",
  "window_too_short", "loop_not_in_dataset",
];

/** The status without its detail: "refused:x" -> "refused". */
export function baseStatus(status: string): string {
  const cut = status.indexOf(":");
  return cut < 0 ? status : status.slice(0, cut);
}

/** The detail of a status ("refused:from_mismatch" -> "from_mismatch"), or "". */
export function statusDetail(status: string): string {
  const cut = status.indexOf(":");
  return cut < 0 ? "" : status.slice(cut + 1);
}

/** Chip level of a status; reviewed:worse is a problem, reviewed:improved is ok. */
export function statusLevel(status: string): StatusLevel {
  const base = baseStatus(status);
  if (base === "refused") return "problem";
  if (base === "reviewed") return reviewLevel(statusDetail(status));
  if (base === "applied") return "ok";
  if (base === "draft" || base === "queued" || base === "reviewing") return "warning";
  return "unused";
}

function reviewLevel(verdict: string): StatusLevel {
  if (verdict === "worse" || verdict === "worse_early") return "problem";
  if (verdict === "improved") return "ok";
  return "unused";
}

/** True while the proposal can still be approved or rejected. */
export function isOpen(status: string): boolean {
  return status === "draft" || status === "queued";
}

/** True for a record that was written to the DCS (also while or after its KPI review). */
export function isWritten(status: string): boolean {
  const base = baseStatus(status);
  return base === "applied" || base === "reviewing" || base === "reviewed";
}

/** The filter group a proposal belongs to. */
export function statusGroup(status: string): string {
  return baseStatus(status);
}

/** True when the record belongs to the loop filter ("" = all) and status group ("" = all). */
export function matchesFilter(p: TuningProposal, loop: string, group: string): boolean {
  return (loop === "" || p.loop_id === loop) && (group === "" || statusGroup(p.status) === group);
}

/** Sorted loop ids that occur in the list. */
export function loopsOf(list: readonly TuningProposal[]): string[] {
  return [...new Set(list.map((p) => p.loop_id))].sort();
}

/** Why the signed-in user may not approve, or an allowed result (the server re-checks). */
export function evaluateApprove(
  p: TuningProposal,
  can: CanResult,
  actor: string | null,
  t: Translate,
): CanResult {
  if (!can.allowed) return can;
  if (p.status !== "queued") return { allowed: false, reason: t("tuning.proposals.reason.notQueued") };
  if (sameActor(actor, p.created_by)) {
    return { allowed: false, reason: t("tuning.proposals.reason.selfApproval", { author: p.created_by }) };
  }
  return { allowed: true, reason: "" };
}

/** Reject is possible for an open record only. */
export function evaluateReject(p: TuningProposal, can: CanResult, t: Translate): CanResult {
  if (!can.allowed) return can;
  if (!isOpen(p.status)) return { allowed: false, reason: t("tuning.proposals.reason.notOpen") };
  return { allowed: true, reason: "" };
}

/** Rollback is possible for a written record that is not itself a rollback of an applied one. */
export function evaluateRollback(p: TuningProposal, can: CanResult, t: Translate): CanResult {
  if (!can.allowed) return can;
  if (!isWritten(p.status)) return { allowed: false, reason: t("tuning.proposals.reason.notApplied") };
  return { allowed: true, reason: "" };
}

/** Seconds until the proposal expires (negative once expired); NaN for an unreadable time. */
export function secondsLeft(expiresAt: string, nowMs: number): number {
  return (Date.parse(expiresAt) - nowMs) / MS_PER_S;
}

/** "h:mm:ss" or "m:ss" text of a positive number of seconds. */
export function formatCountdown(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / S_PER_H);
  const m = Math.floor((total % S_PER_H) / S_PER_MIN);
  const s = total % S_PER_MIN;
  const two = (n: number): string => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${two(m)}:${two(s)}` : `${m}:${two(s)}`;
}

/** The text of the expiry countdown of an open proposal (empty for other statuses). */
export function expiryText(p: TuningProposal, nowMs: number, t: Translate): string {
  if (!isOpen(p.status)) return "";
  const left = secondsLeft(p.expires_at, nowMs);
  if (Number.isNaN(left)) return "";
  if (left <= 0) return t("tuning.proposals.expiry.over");
  return t("tuning.proposals.expiry.left", { time: formatCountdown(left) });
}

/** The locale key and params that explain a refusal code, or the generic text with the code. */
export function codeMessage(code: string, t: Translate): string {
  const bare = code.startsWith("transition_refused") ? "transition_refused" : code;
  if (KNOWN_CODES.includes(bare)) return t(`tuning.err.${bare}`);
  return t("tuning.err.unknown", { code });
}

/** The user-facing text of any failure of a tuning call. */
export function errorText(error: unknown, t: Translate): string {
  if (!(error instanceof TuningApiError)) {
    return t("tuning.err.unknown", { code: error instanceof Error ? error.message : String(error) });
  }
  if (error.status === 428) return t("tuning.err.stepUp");
  if (error.status === 504) return t("tuning.err.timeout");
  if (error.status === 503 && !KNOWN_CODES.includes(error.code)) return t("tuning.err.gatewayDown");
  if (error.status === 403 && !KNOWN_CODES.includes(error.code)) return t("tuning.err.forbidden");
  if (error.code === "") return t("tuning.err.unknown", { code: String(error.status) });
  return codeMessage(error.code, t);
}

/** The text of a reviewed verdict reason code (unknown codes are shown as they are). */
export function reasonText(code: string, t: Translate): string {
  const key = `${WHY_PREFIX}${code}`;
  const text = t(key);
  return text === key || text === "" ? code : text;
}

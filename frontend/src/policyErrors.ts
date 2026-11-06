// frontend/src/policyErrors.ts
/**
 * Maps policy API failures to user-facing text (ADR 013). The server's 409 `detail` codes decide
 * the message; unknown codes and non-API errors fall back to the generic "Policy error" text.
 * Pure: no DOM, no network.
 */

import type { Translate } from "./findings";
import { PolicyError } from "./policyApi";

const CONFLICT_KEYS: Readonly<Record<string, string>> = {
  draft_changed: "policy.reason.draftChanged",
  no_draft: "policy.error.noDraft",
  draft_bad_signature: "policy.error.badSignature",
  policy_path_not_configured: "policy.error.pathNotConfigured",
};

function conflictText(detail: string, t: Translate): string {
  if (detail.startsWith("key_")) return t("policy.error.gatewayKey");
  const key = CONFLICT_KEYS[detail];
  return key ? t(key) : t("policy.error.conflict", { detail });
}

function statusText(err: PolicyError, t: Translate): string {
  if (err.status === 409) return conflictText(err.detail, t);
  if (err.status === 428) return t("policy.error.stepUp");
  if (err.status === 403) return t("policy.error.forbidden", { detail: err.detail });
  if (err.status === 504) return t("policy.error.timeout");
  if (err.status === 422) return err.detail;
  return t("policy.error", { error: err.detail });
}

/** True for the 409 that means "the server draft is not the one you loaded": reload it. */
export function isDraftChanged(err: unknown): boolean {
  return err instanceof PolicyError && err.status === 409 && err.detail === "draft_changed";
}

/** The text shown in the error banner for any failure of a policy request. */
export function policyErrorText(err: unknown, t: Translate): string {
  if (err instanceof PolicyError) return statusText(err, t);
  const message = err instanceof Error ? err.message : String(err);
  return t("policy.error", { error: message });
}

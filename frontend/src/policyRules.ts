// frontend/src/policyRules.ts
/**
 * Pure rules deciding whether Save, Pin and Reload may be used and, when not, why (ADR 013).
 * The reason is the text shown next to the disabled control. No DOM, no network.
 */

import type { CanResult } from "./AuthContext";
import type { Translate } from "./findings";
import { sameActor } from "./policyModel";

/** Actor name the server records when authentication is disabled. */
export const LOCAL_DEV_ACTOR = "local-dev";

const ALLOWED: CanResult = { allowed: true, reason: "" };

function deny(reason: string): CanResult {
  return { allowed: false, reason };
}

/** The signed-in user's name as the server sees it ("local-dev" while auth is disabled). */
export function currentActor(status: string, username: string | null | undefined): string | null {
  if (status === "disabled") return LOCAL_DEV_ACTOR;
  return username ?? null;
}

export interface PinState {
  busy: boolean;
  canPin: CanResult;
  hasDraft: boolean;
  dirty: boolean;
  reviewed: boolean;
  actor: string | null;
  draftAuthor: string | null;
}

/** Pin needs: permission, a saved server draft, no unsaved edits, a second person, a review tick. */
export function evaluatePin(s: PinState, t: Translate): CanResult {
  if (s.busy) return deny(t("policy.reason.busy"));
  if (!s.canPin.allowed) return s.canPin;
  if (!s.hasDraft) return deny(t("policy.reason.noDraft"));
  if (s.dirty) return deny(t("policy.reason.unsavedEdits"));
  if (sameActor(s.actor, s.draftAuthor)) {
    return deny(t("policy.reason.selfPinNotAllowed", { author: s.draftAuthor ?? "" }));
  }
  if (!s.reviewed) return deny(t("policy.reason.reviewRequired"));
  return ALLOWED;
}

/** Reload is safe only while the gateway is known to be off or advisory. */
export function evaluateReload(gatewayMode: string | undefined, busy: boolean, can: CanResult, t: Translate): CanResult {
  if (busy) return deny(t("policy.reason.busy"));
  if (!can.allowed) return can;
  if (gatewayMode === undefined) return deny(t("policy.reason.reloadModeUnknown"));
  if (gatewayMode !== "off" && gatewayMode !== "advisory") {
    return deny(t("policy.reason.reloadModeForbidden", { mode: gatewayMode }));
  }
  return ALLOWED;
}

/** Save needs permission and a document without invalid fields. */
export function evaluateSave(busy: boolean, can: CanResult, invalidFields: number, t: Translate): CanResult {
  if (busy) return deny(t("policy.reason.busy"));
  if (!can.allowed) return can;
  if (invalidFields > 0) return deny(t("policy.reason.validationFailed", { count: invalidFields }));
  return ALLOWED;
}

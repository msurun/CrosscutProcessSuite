// frontend/src/tuningRules.test.ts
// Pure rules of the tuning proposals view: statuses, approve rule, countdown, error mapping.

import { describe, expect, it } from "vitest";
import { TuningApiError } from "./tuningApi";
import {
  baseStatus,
  codeMessage,
  errorText,
  evaluateApprove,
  evaluateReject,
  evaluateRollback,
  expiryText,
  formatCountdown,
  invalidKey,
  isApplying,
  isOpen,
  matchesFilter,
  reasonText,
  reviewUntrusted,
  STATUS_GROUPS,
  statusLevel,
} from "./tuningRules";
import { makeProposal, mockT as t } from "./tuningTestKit";

const ALLOWED = { allowed: true, reason: "" };

describe("status", () => {
  it("splits and rates statuses", () => {
    expect(baseStatus("refused:from_mismatch")).toBe("refused");
    expect(statusLevel("queued")).toBe("warning");
    expect(statusLevel("applied")).toBe("ok");
    expect(statusLevel("reviewed:worse")).toBe("problem");
    expect(statusLevel("reviewed:improved")).toBe("ok");
    expect(statusLevel("refused:x")).toBe("problem");
    expect(statusLevel("rejected")).toBe("unused");
  });

  it("filters by loop and status group", () => {
    const p = makeProposal({ status: "refused:loop_busy" });
    expect(matchesFilter(p, "", "")).toBe(true);
    expect(matchesFilter(p, "FIC101", "refused")).toBe(true);
    expect(matchesFilter(p, "TIC1", "")).toBe(false);
    expect(matchesFilter(p, "", "queued")).toBe(false);
  });
});

describe("approve rule", () => {
  it("refuses the author, normalising case and space", () => {
    const p = makeProposal({ created_by: "Alice " });
    expect(evaluateApprove(p, ALLOWED, "alice", t).allowed).toBe(false);
    expect(evaluateApprove(p, ALLOWED, "bob", t).allowed).toBe(true);
  });

  it("keeps the permission reason first and needs a queued record", () => {
    const denied = { allowed: false, reason: "auth.reason.requires_role", requiredRole: "engineer" };
    expect(evaluateApprove(makeProposal(), denied, "bob", t)).toBe(denied);
    expect(evaluateApprove(makeProposal({ status: "applied" }), ALLOWED, "bob", t).allowed).toBe(false);
  });

  it("allows rollback only for written records", () => {
    expect(evaluateRollback(makeProposal({ status: "reviewed:worse" }), ALLOWED, t).allowed).toBe(true);
    expect(evaluateRollback(makeProposal({ status: "queued" }), ALLOWED, t).allowed).toBe(false);
  });
});

describe("countdown", () => {
  it("formats minutes and hours", () => {
    expect(formatCountdown(65)).toBe("1:05");
    expect(formatCountdown(3725)).toBe("1:02:05");
    expect(formatCountdown(-3)).toBe("0:00");
  });

  it("shows the time left of an open proposal and nothing for a closed one", () => {
    const now = Date.parse("2026-11-05T10:00:00Z");
    const open = makeProposal({ expires_at: "2026-11-05T10:01:05Z" });
    expect(expiryText(open, now, t)).toContain("1:05");
    expect(expiryText(open, now + 120_000, t)).toBe("tuning.proposals.expiry.over");
    expect(expiryText(makeProposal({ status: "applied" }), now, t)).toBe("");
  });
});

describe("error text", () => {
  it("maps the refusal codes of the gateway", () => {
    for (const code of ["from_mismatch", "out_of_limits", "ratio_exceeded", "loop_busy", "expired", "id_conflict",
      "service_cannot_propose_tuning", "proposer_required"]) {
      expect(codeMessage(code, t)).toBe(`tuning.err.${code}`);
    }
  });

  it("maps statuses 403, 428, 504 and 503", () => {
    expect(errorText(new TuningApiError(403, "self_approval", ""), t)).toBe("tuning.err.self_approval");
    expect(errorText(new TuningApiError(403, "forbidden", ""), t)).toBe("tuning.err.forbidden");
    expect(errorText(new TuningApiError(428, "step_up_required", ""), t)).toBe("tuning.err.stepUp");
    expect(errorText(new TuningApiError(504, "gateway did not answer", ""), t)).toBe("tuning.err.timeout");
    expect(errorText(new TuningApiError(503, "gateway not running", ""), t)).toBe("tuning.err.gatewayDown");
    expect(errorText(new TuningApiError(409, "transition_refused: status a -> b", ""), t)).toBe(
      "tuning.err.transition_refused",
    );
  });

  it("falls back to the generic text with the code", () => {
    expect(errorText(new TuningApiError(409, "weird_code", ""), t)).toContain("weird_code");
    expect(errorText(new Error("boom"), t)).toContain("boom");
  });
});

describe("hardened write path", () => {
  const unverified = {
    from_read: { "FIC101.GAIN": null, "FIC101.TI": null },
    to_read: { "FIC101.GAIN": null, "FIC101.TI": null },
    t: "2026-11-05T11:00:00Z",
    approver: "bob",
    source: "gateway_reply",
    invalid: "audit_unverified",
  };

  it("rates and filters the applying status like an open warning", () => {
    expect(statusLevel("applying")).toBe("warning");
    expect(isApplying("applying")).toBe(true);
    expect(isOpen("applying")).toBe(false);
    expect(STATUS_GROUPS).toContain("applying");
    expect(matchesFilter(makeProposal({ status: "applying" }), "", "applying")).toBe(true);
    expect(statusLevel("refused:foreign_pending")).toBe("problem");
  });

  it("disables approve, reject and rollback while applying, with the applying reason", () => {
    const p = makeProposal({ status: "applying" });
    for (const result of [evaluateApprove(p, ALLOWED, "bob", t), evaluateReject(p, ALLOWED, t), evaluateRollback(p, ALLOWED, t)]) {
      expect(result.allowed).toBe(false);
      expect(result.reason).toContain("tuning.proposals.reason.applying");
    }
  });

  it("refuses rollback of an unverified applied block, whatever the reason of invalid", () => {
    const rolled = (applied: object) => evaluateRollback(makeProposal({ status: "reviewed:insufficient_data", applied: applied as never }), ALLOWED, t);
    expect(rolled(unverified).reason).toContain("tuning.proposals.reason.appliedUnverified");
    expect(rolled({ ...unverified, source: "audit", invalid: "audit_chain_broken" }).allowed).toBe(false);
    expect(rolled({ ...unverified, source: "audit", invalid: "param_changed_externally", from_read: {}, to_read: {} }).allowed).toBe(false);
    expect(rolled({ ...unverified, source: "audit", chain_ok: true, invalid: undefined, from_read: { a: 1 }, to_read: { a: null } }).allowed).toBe(false);
    expect(rolled({ ...unverified, source: "audit", chain_ok: true, invalid: undefined, from_read: { a: 1 }, to_read: { a: 2 } }).allowed).toBe(true);
  });

  it("maps the new error codes to their own texts", () => {
    for (const code of ["use_tuning_endpoint", "no_live_values", "applied_unverified", "foreign_pending", "no_history", "applying", "reconcile_required"]) {
      expect(errorText(new TuningApiError(409, code, ""), t)).toBe(`tuning.err.${code}`);
    }
    expect(errorText(new TuningApiError(422, "no_history", "no_history"), t)).toBe("tuning.err.no_history");
    expect(errorText(new TuningApiError(503, "gateway_state_unreadable", ""), t)).toBe("tuning.err.gateway_state_unreadable");
    expect(errorText(new TuningApiError(504, "gateway did not answer", ""), t)).toBe("tuning.err.timeout");
  });

  it("explains each invalid reason and untrusted review reasons", () => {
    expect(invalidKey("audit_unverified")).toBe("tuning.proposals.applied.invalid.audit_unverified");
    expect(invalidKey("audit_chain_broken")).toBe("tuning.proposals.applied.invalid.audit_chain_broken");
    expect(invalidKey("param_changed_externally")).toBe("tuning.proposals.applied.invalid.param_changed_externally");
    expect(invalidKey(true)).toBe("tuning.proposals.applied.invalid.generic");
    expect(reviewUntrusted(["applied_unverified"])).toBe(true);
    expect(reviewUntrusted(["param_changed_externally"])).toBe(true);
    expect(reviewUntrusted(["few_samples"])).toBe(false);
    expect(reasonText("applied_unverified", (k) => (k.endsWith("applied_unverified") ? "no audit" : k))).toBe("no audit");
  });
});

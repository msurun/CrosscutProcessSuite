// frontend/src/tuningRules.test.ts
// Pure rules of the tuning proposals view: statuses, approve rule, countdown, error mapping.

import { describe, expect, it } from "vitest";
import { TuningApiError } from "./tuningApi";
import {
  baseStatus,
  codeMessage,
  errorText,
  evaluateApprove,
  evaluateRollback,
  expiryText,
  formatCountdown,
  matchesFilter,
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

// frontend/src/policyModel.test.ts
/**
 * Unit tests for policyModel pure logic (ADR 013, issues #46/#47).
 * Verifies validation of engineering limits, clamps, timing rules, confusable tag detection,
 * policy diff calculations (loosening vs tightening), and aggregate risk summaries.
 */

import { describe, expect, it } from "vitest";
import {
  diffPolicies,
  docsEqual,
  normalizeActor,
  parseNumberInput,
  sameActor,
  hasUnicodeLookalikes,
  riskSummary,
  validateLimits,
  validateLoopModes,
  validateNonNegativeNumber,
  validatePositiveNumber,
  validateTag,
  validateTarget,
  type PolicyDocument,
  type TargetPolicy,
} from "./policyModel";

const FIXTURE_TARGET: TargetPolicy = {
  limits: [10.0, 50.0],
  max_step: 2.0,
  max_rate_per_s: 1.0,
  min_interval_s: 1.0,
  allowed_loop_modes: ["CAS", "AUTO"],
  hold_off_s: 5.0,
  watchdog_s: 15.0,
  readback_tolerance: 0.2,
};

const FIXTURE_DOC: PolicyDocument = {
  version: 1,
  mode: "advisory",
  targets: {
    "FIC101.SP": { ...FIXTURE_TARGET },
  },
};

describe("policyModel - validateTag identifiers & duplicates", () => {
  it("accepts valid ASCII process tag identifiers", () => {
    expect(validateTag("FIC101.SP", [])).toBeNull();
    expect(validateTag("TIC-200_A:1", [])).toBeNull();
  });

  it("rejects empty, whitespace-only or oversized tags", () => {
    expect(validateTag("", [])).toBe("policy.validation.required");
    expect(validateTag("   ", [])).toBe("policy.validation.required");
    expect(validateTag("a".repeat(129), [])).toBe("policy.validation.tooLarge");
  });

  it("rejects invalid characters in tags", () => {
    expect(validateTag("FIC 101", [])).toBe("policy.validation.tagInvalid");
    expect(validateTag("FIC#101", [])).toBe("policy.validation.tagInvalid");
    expect(validateTag("FIC@SP", [])).toBe("policy.validation.tagInvalid");
  });

  it("detects duplicate target tags unless updating itself", () => {
    expect(validateTag("FIC101.SP", ["FIC101.SP", "TIC102.SP"])).toBe("policy.validation.tagDuplicate");
    expect(validateTag("FIC101.SP", ["FIC101.SP"], "FIC101.SP")).toBeNull();
  });
});

describe("policyModel - confusable checks", () => {
  it("identifies Unicode lookalike homoglyphs and non-ASCII characters", () => {
    expect(hasUnicodeLookalikes("FIC101.SP")).toBe(false);
    expect(hasUnicodeLookalikes("FIC101.SP\u0430")).toBe(true);
    expect(hasUnicodeLookalikes("FIC101.\u03BF")).toBe(true);
    expect(hasUnicodeLookalikes("FIC101\uFF1ASP")).toBe(true);
  });
});

describe("policyModel - numeric and limits validators", () => {
  it("validates positive numbers (> 0)", () => {
    expect(validatePositiveNumber(5)).toBeNull();
    expect(validatePositiveNumber(0)).toBe("policy.validation.positive");
    expect(validatePositiveNumber(-1)).toBe("policy.validation.positive");
    expect(validatePositiveNumber(NaN)).toBe("policy.validation.finiteNumber");
    expect(validatePositiveNumber(Infinity)).toBe("policy.validation.finiteNumber");
    expect(validatePositiveNumber(1e13)).toBe("policy.validation.tooLarge");
  });

  it("validates non-negative numbers (>= 0)", () => {
    expect(validateNonNegativeNumber(0)).toBeNull();
    expect(validateNonNegativeNumber(2.5)).toBeNull();
    expect(validateNonNegativeNumber(-0.1)).toBe("policy.validation.nonNegative");
    expect(validateNonNegativeNumber(NaN)).toBe("policy.validation.finiteNumber");
  });

  it("validates range limits [low, high]", () => {
    expect(validateLimits([0, 100])).toBeNull();
    expect(validateLimits([-20, -10])).toBeNull();
    expect(validateLimits([100, 50])).toBe("policy.validation.limitsOrder");
    expect(validateLimits([NaN, 50])).toBe("policy.validation.finiteNumber");
    expect(validateLimits([0, Infinity])).toBe("policy.validation.finiteNumber");
    expect(validateLimits([10])).toBe("policy.validation.required");
  });
});

describe("policyModel - loop modes & target object validators", () => {
  it("validates allowed loop modes", () => {
    expect(validateLoopModes(["CAS", "AUTO"])).toBeNull();
    expect(validateLoopModes([])).toBe("policy.validation.allowedModesEmpty");
    expect(validateLoopModes([""])).toBe("policy.validation.allowedModesEmpty");
    expect(validateLoopModes(["CAS", "CAS"])).toBe("policy.validation.tagDuplicate");
  });

  it("validates entire TargetPolicy object", () => {
    expect(validateTarget(FIXTURE_TARGET)).toEqual({});
    const invalidTarget: TargetPolicy = {
      ...FIXTURE_TARGET,
      limits: [100, 50],
      max_step: -1,
      min_interval_s: -2,
    };
    const errors = validateTarget(invalidTarget);
    expect(errors.limits).toBe("policy.validation.limitsOrder");
    expect(errors.max_step).toBe("policy.validation.positive");
    expect(errors.min_interval_s).toBe("policy.validation.nonNegative");
  });
});

describe("policyModel - diffPolicies mode & target presence", () => {
  it("detects global mode transitions", () => {
    const higherDraft: PolicyDocument = { ...FIXTURE_DOC, mode: "confirm" };
    const diffUp = diffPolicies(FIXTURE_DOC, higherDraft);
    expect(diffUp.modeChange?.loosening).toBe(true);

    const lowerDraft: PolicyDocument = { ...FIXTURE_DOC, mode: "off" };
    const diffDown = diffPolicies(FIXTURE_DOC, lowerDraft);
    expect(diffDown.modeChange?.loosening).toBe(false);
  });

  it("detects target addition (loosening) and target removal (tightening)", () => {
    const addedDraft: PolicyDocument = {
      ...FIXTURE_DOC,
      targets: {
        ...FIXTURE_DOC.targets,
        "TIC102.SP": { ...FIXTURE_TARGET },
      },
    };
    const diffAdded = diffPolicies(FIXTURE_DOC, addedDraft);
    const addedTarget = diffAdded.targetDiffs.find((t) => t.tag === "TIC102.SP");
    expect(addedTarget?.status).toBe("added");
    expect(addedTarget?.loosening).toBe(true);

    const emptyDraft: PolicyDocument = { ...FIXTURE_DOC, targets: {} };
    const diffRemoved = diffPolicies(FIXTURE_DOC, emptyDraft);
    const removedTarget = diffRemoved.targetDiffs.find((t) => t.tag === "FIC101.SP");
    expect(removedTarget?.status).toBe("removed");
    expect(removedTarget?.loosening).toBe(false);
  });
});

describe("policyModel - diffPolicies numerical constraints", () => {
  it("evaluates engineering limits widening as loosening and narrowing as tightening", () => {
    const widenedDraft: PolicyDocument = {
      ...FIXTURE_DOC,
      targets: { "FIC101.SP": { ...FIXTURE_TARGET, limits: [5.0, 60.0] } },
    };
    const diffWidened = diffPolicies(FIXTURE_DOC, widenedDraft);
    const limitChangeW = diffWidened.targetDiffs[0].changes.find((c) => c.field === "limits");
    expect(limitChangeW?.loosening).toBe(true);

    const narrowedDraft: PolicyDocument = {
      ...FIXTURE_DOC,
      targets: { "FIC101.SP": { ...FIXTURE_TARGET, limits: [15.0, 45.0] } },
    };
    const diffNarrowed = diffPolicies(FIXTURE_DOC, narrowedDraft);
    const limitChangeN = diffNarrowed.targetDiffs[0].changes.find((c) => c.field === "limits");
    expect(limitChangeN?.loosening).toBe(false);
  });

  it("evaluates max_step and max_rate: larger is loosening, smaller is tightening", () => {
    const higherStep: PolicyDocument = {
      ...FIXTURE_DOC,
      targets: { "FIC101.SP": { ...FIXTURE_TARGET, max_step: 5.0, max_rate_per_s: 0.5 } },
    };
    const diff = diffPolicies(FIXTURE_DOC, higherStep);
    const stepChange = diff.targetDiffs[0].changes.find((c) => c.field === "max_step");
    const rateChange = diff.targetDiffs[0].changes.find((c) => c.field === "max_rate_per_s");
    expect(stepChange?.loosening).toBe(true);
    expect(rateChange?.loosening).toBe(false);
  });

  it("evaluates min_interval and hold_off: smaller is loosening, larger is tightening", () => {
    const fasterWrites: PolicyDocument = {
      ...FIXTURE_DOC,
      targets: { "FIC101.SP": { ...FIXTURE_TARGET, min_interval_s: 0.5, hold_off_s: 10.0 } },
    };
    const diff = diffPolicies(FIXTURE_DOC, fasterWrites);
    const intervalChange = diff.targetDiffs[0].changes.find((c) => c.field === "min_interval_s");
    const holdOffChange = diff.targetDiffs[0].changes.find((c) => c.field === "hold_off_s");
    expect(intervalChange?.loosening).toBe(true);
    expect(holdOffChange?.loosening).toBe(false);
  });

  it("evaluates watchdog and readback tolerance: larger is loosening, smaller is tightening", () => {
    const relaxed: PolicyDocument = {
      ...FIXTURE_DOC,
      targets: { "FIC101.SP": { ...FIXTURE_TARGET, watchdog_s: 30.0, readback_tolerance: 0.05 } },
    };
    const diff = diffPolicies(FIXTURE_DOC, relaxed);
    const wdChange = diff.targetDiffs[0].changes.find((c) => c.field === "watchdog_s");
    const tolChange = diff.targetDiffs[0].changes.find((c) => c.field === "readback_tolerance");
    expect(wdChange?.loosening).toBe(true);
    expect(tolChange?.loosening).toBe(false);
  });
});

describe("policyModel - diffPolicies modes & extra fields", () => {
  it("evaluates allowed loop modes: adding mode is loosening, removing is tightening", () => {
    const addedMode: PolicyDocument = {
      ...FIXTURE_DOC,
      targets: { "FIC101.SP": { ...FIXTURE_TARGET, allowed_loop_modes: ["CAS", "AUTO", "RSP"] } },
    };
    const diffAdd = diffPolicies(FIXTURE_DOC, addedMode);
    const modeChangeA = diffAdd.targetDiffs[0].changes.find((c) => c.field === "allowed_loop_modes");
    expect(modeChangeA?.loosening).toBe(true);

    const removedMode: PolicyDocument = {
      ...FIXTURE_DOC,
      targets: { "FIC101.SP": { ...FIXTURE_TARGET, allowed_loop_modes: ["CAS"] } },
    };
    const diffRem = diffPolicies(FIXTURE_DOC, removedMode);
    const modeChangeR = diffRem.targetDiffs[0].changes.find((c) => c.field === "allowed_loop_modes");
    expect(modeChangeR?.loosening).toBe(false);
  });

  it("preserves and flags extra document properties", () => {
    const extraLive: PolicyDocument = { ...FIXTURE_DOC, site_id: "site-1" };
    const extraDraft: PolicyDocument = { ...FIXTURE_DOC, site_id: "site-2" };
    const diff = diffPolicies(extraLive, extraDraft);
    expect(diff.extraFieldChanges.length).toBe(1);
    expect(diff.extraFieldChanges[0].field).toBe("site_id");
  });
});

describe("policyModel - riskSummary", () => {
  it("summarizes risk as 'none' when diff has no changes", () => {
    const noDiff = diffPolicies(FIXTURE_DOC, FIXTURE_DOC);
    expect(riskSummary(noDiff).level).toBe("none");
  });

  it("summarizes risk as 'low' for tightening changes", () => {
    const tighteningDoc: PolicyDocument = {
      ...FIXTURE_DOC,
      targets: { "FIC101.SP": { ...FIXTURE_TARGET, max_step: 1.0 } },
    };
    const tightSummary = riskSummary(diffPolicies(FIXTURE_DOC, tighteningDoc));
    expect(tightSummary.level).toBe("low");
    expect(tightSummary.tighteningCount).toBe(1);
  });

  it("summarizes risk as 'high' when loosening changes are present", () => {
    const looseningDoc: PolicyDocument = {
      ...FIXTURE_DOC,
      mode: "confirm",
      targets: { "FIC101.SP": { ...FIXTURE_TARGET, max_step: 10.0 } },
    };
    const looseSummary = riskSummary(diffPolicies(FIXTURE_DOC, looseningDoc));
    expect(looseSummary.level).toBe("high");
    expect(looseSummary.looseningCount).toBeGreaterThan(0);
  });
});

describe("policyModel - parseNumberInput", () => {
  it("keeps empty and blank text invalid (NaN), never 0", () => {
    expect(parseNumberInput("")).toBeNaN();
    expect(parseNumberInput("   ")).toBeNaN();
    expect(validatePositiveNumber(parseNumberInput(""))).toBe("policy.validation.finiteNumber");
  });

  it("accepts plain decimals and exponent notation", () => {
    expect(parseNumberInput("12.5")).toBe(12.5);
    expect(parseNumberInput("1e5")).toBe(100000);
    expect(parseNumberInput("2.5E-3")).toBe(0.0025);
  });

  it("turns NaN, Infinity and overflow into NaN", () => {
    expect(parseNumberInput("abc")).toBeNaN();
    expect(parseNumberInput("Infinity")).toBeNaN();
    expect(parseNumberInput("-Infinity")).toBeNaN();
    expect(parseNumberInput("1e999")).toBeNaN();
  });

  it("normalises negative zero to 0", () => {
    expect(Object.is(parseNumberInput("-0"), 0)).toBe(true);
    expect(validatePositiveNumber(parseNumberInput("-0"))).toBe("policy.validation.positive");
  });
});

describe("policyModel - actor comparison like the server", () => {
  it("normalises NFKC, whitespace, case and casefold", () => {
    expect(normalizeActor("  Jan   Kowalski ")).toBe("jan kowalski");
    expect(normalizeActor("Ａdmin")).toBe("admin");
    expect(normalizeActor("Straße")).toBe("strasse");
  });

  it("treats look-alike spellings of one actor as the same actor", () => {
    expect(sameActor("Engineer_Author", " engineer_author ")).toBe(true);
    expect(sameActor("a b", "a		b")).toBe(true);
    expect(sameActor("alice", "bob")).toBe(false);
    expect(sameActor(null, "bob")).toBe(false);
    expect(sameActor("alice", "")).toBe(false);
  });
});

describe("policyModel - docsEqual", () => {
  it("ignores key order but sees value changes and NaN", () => {
    const reordered = { targets: FIXTURE_DOC.targets, mode: FIXTURE_DOC.mode, version: 1 } as PolicyDocument;
    expect(docsEqual(FIXTURE_DOC, reordered)).toBe(true);
    const changed = { ...FIXTURE_DOC, mode: "off" } as PolicyDocument;
    expect(docsEqual(FIXTURE_DOC, changed)).toBe(false);
    const nan = { ...FIXTURE_DOC, targets: { "FIC101.SP": { ...FIXTURE_TARGET, max_step: Number.NaN } } };
    expect(docsEqual(FIXTURE_DOC, nan)).toBe(false);
  });
});

describe("policyModel - diff params and mode without live policy", () => {
  it("carries placeholder values for every explanation", () => {
    const draft: PolicyDocument = {
      ...FIXTURE_DOC,
      mode: "confirm",
      targets: { "FIC101.SP": { ...FIXTURE_TARGET, max_step: 9, limits: [0, 60], allowed_loop_modes: ["CAS", "MAN"] } },
    };
    const diff = diffPolicies(FIXTURE_DOC, draft);
    expect(diff.modeChange?.params).toEqual({ oldMode: "advisory", newMode: "confirm" });
    const fields = Object.fromEntries(diff.targetDiffs[0].changes.map((c) => [c.field, c.params]));
    expect(fields.max_step).toEqual({ oldVal: 2, newVal: 9 });
    expect(fields.limits).toEqual({ oldLo: 10, oldHi: 50, newLo: 0, newHi: 60 });
    expect(fields.allowed_loop_modes).toEqual({ added: "MAN", removed: "AUTO" });
  });

  it("flags a non-off draft mode as loosening when there is no live policy", () => {
    const diff = diffPolicies(null, { ...FIXTURE_DOC, mode: "confirm", targets: {} });
    expect(diff.modeChange?.loosening).toBe(true);
    expect(diff.hasChanges).toBe(true);
    expect(diffPolicies(null, { ...FIXTURE_DOC, mode: "off", targets: {} }).modeChange).toBeNull();
  });

  it("treats a new target as loosening and a removed target as tightening in the risk summary", () => {
    const added = riskSummary(diffPolicies({ ...FIXTURE_DOC, targets: {} }, FIXTURE_DOC));
    expect(added.looseningCount).toBe(1);
    expect(added.level).not.toBe("low");
    const removed = riskSummary(diffPolicies(FIXTURE_DOC, { ...FIXTURE_DOC, targets: {} }));
    expect(removed.tighteningCount).toBe(1);
    expect(removed.level).toBe("low");
  });

  it("treats an unknown mode as loosening", () => {
    const odd = { ...FIXTURE_DOC, mode: "turbo" } as unknown as PolicyDocument;
    expect(diffPolicies(FIXTURE_DOC, odd).modeChange?.loosening).toBe(true);
  });
});

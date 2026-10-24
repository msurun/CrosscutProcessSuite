// Behaviour tests of the valve stroke test screen logic (reducer, form parsing,
// procedure sentences and error messages). The reducer is the contract the
// component relies on, so every rule in valveTest.ts gets one test here.
import { describe, expect, it } from "vitest";
import type { ValveAnalysis, ValvePlan, ValveProcedureStep } from "./api";
import { ApiError } from "./api";
import type { Translate } from "./findings";
import {
  defaultSettings,
  initialState,
  parseSettings,
  procedureSentence,
  valveErrorMessage,
  valveReducer,
  type Settings,
  type ValveState,
} from "./valveTest";

/** Fake translator: keeps the key visible and serialises params so tests stay readable. */
const translate: Translate = (key, params) => key + (params ? JSON.stringify(params) : "");

const samplePlan: ValvePlan = {
  op_start: 50,
  dwell_s: 120,
  op_low: 0,
  op_high: 100,
  pv_band: null,
  step_sizes: [1, 0.25],
  steps_per_leg: [4, 12],
  n_steps: 8,
  total_s: 960,
  steps: [],
  procedure: [],
};

const sampleAnalysis: ValveAnalysis = {
  result: {
    deadband: 0.5,
    deadband_bracket: [0.25, 1],
    deadband_lower_bound: null,
    resolution_le: 0.25,
    gain: 1,
    sigma_pv: 0.01,
    pv_left_band: false,
    reason_code: "",
    reason: "",
    moves: [],
  },
  record: { n_samples: 100, start_s: 0, end_s: 100, series: { t_s: [], op: [], pv: [] } },
};

/** A state on the checklist screen with a plan and the given checks. */
function checklistState(checks: [boolean, boolean, boolean]): ValveState {
  return { ...initialState(), phase: "checklist", plan: samplePlan, checks };
}

describe("defaultSettings", () => {
  it("opens with the documented default test", () => {
    expect(defaultSettings()).toEqual({
      opStart: "50",
      dwellS: "120",
      opLow: "0",
      opHigh: "100",
      pvBand: "",
      stepSizes: "1, 0.25",
      stepsPerLeg: "4, 12",
    });
  });
});

describe("parseSettings", () => {
  it("accepts the default settings", () => {
    const result = parseSettings(defaultSettings());
    expect(result.ok).toBe(true);
  });

  it("turns the defaults into a plan request with parsed lists", () => {
    const result = parseSettings(defaultSettings());
    expect(result).toEqual({
      ok: true,
      request: { op_start: 50, dwell_s: 120, op_low: 0, op_high: 100, step_sizes: [1, 0.25], steps_per_leg: [4, 12] },
    });
  });

  it("reads a decimal comma as a decimal point", () => {
    const result = parseSettings({ ...defaultSettings(), opStart: "12,5" });
    expect(result.ok && result.request.op_start).toBe(12.5);
  });

  it("ignores surrounding spaces", () => {
    const result = parseSettings({ ...defaultSettings(), dwellS: "  60  " });
    expect(result.ok && result.request.dwell_s).toBe(60);
  });

  it("rejects a non-numeric op start", () => {
    expect(parseSettings({ ...defaultSettings(), opStart: "abc" })).toEqual({ ok: false, field: "opStart" });
  });

  it("rejects a fractional dwell time", () => {
    expect(parseSettings({ ...defaultSettings(), dwellS: "1.5" })).toEqual({ ok: false, field: "dwellS" });
  });

  it("rejects a zero dwell time", () => {
    expect(parseSettings({ ...defaultSettings(), dwellS: "0" })).toEqual({ ok: false, field: "dwellS" });
  });

  it("rejects an empty op low", () => {
    expect(parseSettings({ ...defaultSettings(), opLow: "" })).toEqual({ ok: false, field: "opLow" });
  });

  it("rejects an empty op high", () => {
    expect(parseSettings({ ...defaultSettings(), opHigh: "" })).toEqual({ ok: false, field: "opHigh" });
  });

  it("rejects a zero PV band", () => {
    expect(parseSettings({ ...defaultSettings(), pvBand: "0" })).toEqual({ ok: false, field: "pvBand" });
  });

  it("accepts a positive PV band", () => {
    const result = parseSettings({ ...defaultSettings(), pvBand: "2.5" });
    expect(result.ok && result.request.pv_band).toBe(2.5);
  });

  it("omits the PV band from the request when blank", () => {
    const result = parseSettings({ ...defaultSettings(), pvBand: "  " });
    expect(result.ok && result.request.pv_band).toBeUndefined();
    expect(result.ok && "pv_band" in result.request).toBe(false);
  });

  it("omits the step sizes when the list is blank", () => {
    const result = parseSettings({ ...defaultSettings(), stepSizes: "" });
    expect(result.ok && "step_sizes" in result.request).toBe(false);
  });

  it("omits the steps per leg when the list is blank", () => {
    const result = parseSettings({ ...defaultSettings(), stepsPerLeg: "" });
    expect(result.ok && "steps_per_leg" in result.request).toBe(false);
  });

  it("splits step sizes on semicolons too", () => {
    const result = parseSettings({ ...defaultSettings(), stepSizes: "1; 0,5" });
    expect(result.ok && result.request.step_sizes).toEqual([1, 0.5]);
  });

  it("rejects a non-positive step size", () => {
    expect(parseSettings({ ...defaultSettings(), stepSizes: "1, 0" })).toEqual({ ok: false, field: "stepSizes" });
  });

  it("rejects a steps per leg value that is not an integer", () => {
    expect(parseSettings({ ...defaultSettings(), stepsPerLeg: "2.5" })).toEqual({ ok: false, field: "stepsPerLeg" });
  });

  it("reports the first invalid field in the documented order", () => {
    const broken: Settings = { ...defaultSettings(), opStart: "x", opLow: "y", stepSizes: "0" };
    expect(parseSettings(broken)).toEqual({ ok: false, field: "opStart" });
  });

  it("reports pvBand before stepSizes when both are wrong", () => {
    const broken: Settings = { ...defaultSettings(), pvBand: "-1", stepSizes: "0" };
    expect(parseSettings(broken)).toEqual({ ok: false, field: "pvBand" });
  });
});

describe("valveReducer editSetting", () => {
  it("updates the setting and clears the error", () => {
    const withError: ValveState = { ...initialState(), error: { code: null, field: null, message: "x" } };
    const next = valveReducer(withError, { type: "editSetting", key: "dwellS", value: "60" });
    expect(next.settings.dwellS).toBe("60");
    expect(next.error).toBeNull();
  });

  it("drops an existing plan and returns to setup", () => {
    const planned = checklistState([true, true, true]);
    const next = valveReducer(planned, { type: "editSetting", key: "dwellS", value: "60" });
    expect(next.phase).toBe("setup");
    expect(next.plan).toBeNull();
    expect(next.checks).toEqual([false, false, false]);
  });

  it("keeps the phase when no plan existed", () => {
    const next = valveReducer(initialState(), { type: "editSetting", key: "opStart", value: "40" });
    expect(next.phase).toBe("setup");
  });
});

describe("valveReducer planning", () => {
  it("sets busy and clears the error when a plan is requested", () => {
    const withError: ValveState = { ...initialState(), error: { code: null, field: null, message: "x" } };
    const next = valveReducer(withError, { type: "planRequested" });
    expect(next.busy).toBe(true);
    expect(next.error).toBeNull();
  });

  it("stores the plan and resets the checks when it is ready", () => {
    const busy: ValveState = { ...initialState(), busy: true };
    const next = valveReducer(busy, { type: "planReady", plan: samplePlan });
    expect(next.busy).toBe(false);
    expect(next.phase).toBe("checklist");
    expect(next.plan).toBe(samplePlan);
    expect(next.checks).toEqual([false, false, false]);
  });
});

describe("valveReducer checklist", () => {
  it("flips one check box", () => {
    const next = valveReducer(checklistState([false, false, false]), { type: "toggleCheck", index: 1 });
    expect(next.checks).toEqual([false, true, false]);
  });

  it("refuses to accept the checklist while a box is unticked", () => {
    const state = checklistState([true, true, false]);
    expect(valveReducer(state, { type: "acceptChecklist" })).toBe(state);
  });

  it("moves to the plan screen when all boxes are ticked", () => {
    const next = valveReducer(checklistState([true, true, true]), { type: "acceptChecklist" });
    expect(next.phase).toBe("plan");
  });
});

describe("valveReducer showRecord", () => {
  it("moves from the plan screen to the record screen", () => {
    const state: ValveState = { ...checklistState([true, true, true]), phase: "plan" };
    expect(valveReducer(state, { type: "showRecord" }).phase).toBe("record");
  });

  it("is ignored when not on the plan screen", () => {
    const state = initialState();
    expect(valveReducer(state, { type: "showRecord" })).toBe(state);
  });
});

describe("valveReducer analysis", () => {
  it("sets busy and clears the error when analysis is requested", () => {
    const next = valveReducer(initialState(), { type: "analysisRequested" });
    expect(next.busy).toBe(true);
    expect(next.error).toBeNull();
  });

  it("stores the analysis and shows the result", () => {
    const busy: ValveState = { ...initialState(), busy: true };
    const next = valveReducer(busy, { type: "analysed", analysis: sampleAnalysis });
    expect(next.busy).toBe(false);
    expect(next.phase).toBe("result");
    expect(next.analysis).toBe(sampleAnalysis);
  });

  it("records the error and clears busy on failure, keeping the phase", () => {
    const busy: ValveState = { ...initialState(), busy: true, phase: "record" };
    const error = { code: "no_gain", field: null, message: "no move" };
    const next = valveReducer(busy, { type: "failed", error });
    expect(next.busy).toBe(false);
    expect(next.error).toEqual(error);
    expect(next.phase).toBe("record");
  });
});

describe("valveReducer backTo", () => {
  it("moves to an earlier phase", () => {
    const state: ValveState = { ...initialState(), phase: "result", analysis: sampleAnalysis };
    expect(valveReducer(state, { type: "backTo", phase: "record" }).phase).toBe("record");
  });

  it("ignores a request for the same phase", () => {
    const state: ValveState = { ...initialState(), phase: "plan" };
    expect(valveReducer(state, { type: "backTo", phase: "plan" })).toBe(state);
  });

  it("ignores a request for a later phase", () => {
    const state: ValveState = { ...initialState(), phase: "checklist" };
    expect(valveReducer(state, { type: "backTo", phase: "result" })).toBe(state);
  });

  it("keeps settings and drops plan, checks and analysis when going back to setup", () => {
    const state: ValveState = {
      ...initialState(),
      phase: "result",
      plan: samplePlan,
      analysis: sampleAnalysis,
      checks: [true, true, true],
    };
    const next = valveReducer(state, { type: "backTo", phase: "setup" });
    expect(next.plan).toBeNull();
    expect(next.analysis).toBeNull();
    expect(next.checks).toEqual([false, false, false]);
    expect(next.settings).toEqual(state.settings);
  });

  it("keeps the plan and resets the checks when going back to the checklist", () => {
    const state: ValveState = { ...initialState(), phase: "plan", plan: samplePlan, checks: [true, true, true] };
    const next = valveReducer(state, { type: "backTo", phase: "checklist" });
    expect(next.plan).toBe(samplePlan);
    expect(next.checks).toEqual([false, false, false]);
  });
});

describe("valveReducer reset", () => {
  it("returns the initial state with the same settings", () => {
    const state: ValveState = { ...initialState(), phase: "result", plan: samplePlan, settings: { ...defaultSettings(), dwellS: "60" } };
    const next = valveReducer(state, { type: "reset" });
    expect(next.phase).toBe("setup");
    expect(next.plan).toBeNull();
    expect(next.settings.dwellS).toBe("60");
  });
});

describe("procedureSentence", () => {
  it("translates a manual step without parameters", () => {
    expect(procedureSentence(translate, { code: "manual", params: {} })).toBe("valve.plan.step.manual");
  });

  it("translates an abort without a band", () => {
    const step: ValveProcedureStep = { code: "abort", params: { op_start: 50 } };
    expect(procedureSentence(translate, step)).toContain("valve.plan.step.abort");
  });

  it("translates an abort with a band and both numbers", () => {
    const step: ValveProcedureStep = { code: "abort", params: { op_start: 50, pv_band: 2.5 } };
    expect(procedureSentence(translate, step)).toBe(
      'valve.plan.step.abortBand{"band":"2.50","op":"50.00"}',
    );
  });

  it("translates a set_start step with op and dwell", () => {
    const step: ValveProcedureStep = { code: "set_start", params: { op: 50, dwell_s: 120 } };
    expect(procedureSentence(translate, step)).toBe('valve.plan.step.set_start{"op":"50.00","dwell":"120"}');
  });

  it("translates a step with op and dwell", () => {
    const step: ValveProcedureStep = { code: "step", params: { op: 55, dwell_s: 120 } };
    expect(procedureSentence(translate, step)).toBe('valve.plan.step.step{"op":"55.00","dwell":"120"}');
  });

  it("translates a return_auto step with op only", () => {
    const step: ValveProcedureStep = { code: "return_auto", params: { op: 50 } };
    expect(procedureSentence(translate, step)).toBe('valve.plan.step.return_auto{"op":"50.00"}');
  });
});

describe("valveErrorMessage", () => {
  it("uses the code-specific template for an ApiError with a code", () => {
    const error = new ApiError(400, "bad", { code: "some_code" });
    expect(valveErrorMessage(translate, error)).toBe('valve.error.code.some_code{"message":"bad"}');
  });

  it("uses the generic template for an ApiError without a code", () => {
    expect(valveErrorMessage(translate, new ApiError(500, "boom"))).toBe('valve.error.other{"message":"boom"}');
  });

  it("uses the network template for any other thrown value", () => {
    expect(valveErrorMessage(translate, new Error("offline"))).toBe("valve.error.network");
  });
});

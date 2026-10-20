// src/testFixtures.ts
// Shared builders for tests: a fully populated LoopSummary, so a test states only what it cares about.

import type { LoopSummary } from "./api";

/** A healthy, fully assessed loop; pass overrides for the fields a test is about. */
export function makeLoop(overrides: Partial<LoopSummary> = {}): LoopSummary {
  return {
    name: "Loop A",
    pv: "PV",
    sp: "SP",
    out: "OUT",
    mode: "AUTO",
    unit: "degC",
    status: "ok",
    health_percent: 80,
    classification: "ok",
    findings: [],
    service_percent: 100,
    saturation_percent: 0,
    harris_index: 0.7,
    oscillation_period_s: null,
    oscillation_method: null,
    stiction_verdict: "no_stiction",
    stiction_suspicion: null,
    stiction_advice: "not_ranked",
    valve_travel_per_h: null,
    valve_reversals_per_h: null,
    out_quantisation_ratio: null,
    valve_sizing_hint: null,
    not_assessed: [],
    same_period_as: [],
    next_action: { code: "none", params: {} },
    priority_rank: 1,
    sparkline: [1, 2, 3, 2],
    ...overrides,
  };
}

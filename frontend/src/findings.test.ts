// Unit tests for findings.ts: translated finding text, next-step hints and loop sort order.
// They check that the first finding is shown, that a loop without findings gets the ok hint,
// and that loops sort by status (problem, warning, ok, unused) and then by health.
import { describe, expect, it } from "vitest";

import type { LoopSummary } from "./api";
import { compareLoops, findingText, mainFindingText, nextStepTexts, type Translate } from "./findings";

/**
 * Fake translator for tests: it echoes the key and appends the params as JSON,
 * so assertions can read which translation key was used.
 */
const t: Translate = (key, params) => key + (params ? JSON.stringify(params) : "");

/**
 * Builds a LoopSummary where every field has a sensible "everything is fine"
 * default, so each test overrides only the fields it cares about.
 */
function makeLoop(overrides: Partial<LoopSummary> = {}): LoopSummary {
  return {
    name: "loop",
    pv: "pv",
    sp: "sp",
    out: "out",
    mode: "auto",
    unit: "bar",
    status: "ok",
    health_percent: 80,
    classification: "ok",
    findings: [],
    service_percent: 100,
    saturation_percent: 0,
    harris_index: 0.7,
    oscillation_period_s: null,
    stiction_verdict: "no_stiction",
    sparkline: [],
    ...overrides,
  };
}

describe("findingText", () => {
  it("uses the finding code as the translation key", () => {
    const finding = { code: "oscillating", params: { period_s: 12 } };

    const text = findingText(t, finding);

    expect(text).toBe('finding.oscillating{"period_s":12}');
  });
});

describe("mainFindingText", () => {
  it("returns the text of the first finding", () => {
    const loop = makeLoop({
      findings: [
        { code: "oscillating", params: { period_s: 12 } },
        { code: "saturated", params: { percent: 90 } },
      ],
    });

    const text = mainFindingText(t, loop);

    expect(text).toBe('finding.oscillating{"period_s":12}');
  });

  it("falls back to the no-findings message when the loop has no findings", () => {
    const loop = makeLoop({ findings: [] });

    const text = mainFindingText(t, loop);

    expect(text).toBe("loops.noFindings");
  });
});

describe("nextStepTexts", () => {
  it("maps every finding to its next-step translation", () => {
    const loop = makeLoop({
      findings: [
        { code: "oscillating", params: { period_s: 12 } },
        { code: "saturated", params: { percent: 90 } },
      ],
    });

    const texts = nextStepTexts(t, loop);

    expect(texts).toEqual(["next.oscillating", "next.saturated"]);
  });

  it("returns the ok next step when the loop has no findings", () => {
    const loop = makeLoop({ findings: [] });

    const texts = nextStepTexts(t, loop);

    expect(texts).toEqual(["next.ok"]);
  });
});

describe("compareLoops", () => {
  const problem = makeLoop({ name: "problem", status: "problem", health_percent: 10 });
  const warning = makeLoop({ name: "warning", status: "warning", health_percent: 50 });
  const ok = makeLoop({ name: "ok", status: "ok", health_percent: 90 });
  const unused = makeLoop({ name: "unused", status: "unused", health_percent: 100 });

  it("sorts statuses as problem, warning, ok, unused", () => {
    const loops = [unused, ok, warning, problem];

    const sorted = [...loops].sort(compareLoops);

    expect(sorted.map((loop) => loop.name)).toEqual(["problem", "warning", "ok", "unused"]);
  });

  it("breaks ties inside a status by lower health first", () => {
    const healthier = makeLoop({ name: "healthier", status: "warning", health_percent: 70 });
    const sicker = makeLoop({ name: "sicker", status: "warning", health_percent: 30 });

    const sorted = [healthier, sicker].sort(compareLoops);

    expect(sorted.map((loop) => loop.name)).toEqual(["sicker", "healthier"]);
  });

  it("sorts a loop with null health last within its status", () => {
    const unknown = makeLoop({ name: "unknown", status: "warning", health_percent: null });
    const known = makeLoop({ name: "known", status: "warning", health_percent: 60 });

    const sorted = [unknown, known].sort(compareLoops);

    expect(sorted.map((loop) => loop.name)).toEqual(["known", "unknown"]);
  });
});

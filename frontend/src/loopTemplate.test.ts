// frontend/src/loopTemplate.test.ts
// Request method, path, body and CSRF header of the loop template calls, plus the pure
// formatting and validation helpers the editor relies on.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setCsrfToken } from "./authApi";
import {
  LoopTemplateApiError,
  formatDynamics,
  formatTuning,
  invalidRangeFields,
  listLoopTemplates,
  saveLoopTemplate,
  templateBody,
  toggleValue,
  type LoopTemplate,
} from "./loopTemplate";

/** A small valid template used by the assertions. */
function makeTemplate(overrides: Partial<LoopTemplate> = {}): LoopTemplate {
  return {
    key: "flow",
    label: "Flow",
    description: "Fast and tight",
    process_kind: "self_regulating",
    dynamics: {
      gain_min: 0.5,
      gain_max: 5,
      time_constant_s_min: 5,
      time_constant_s_max: 120,
      dead_time_s_min: 1,
      dead_time_s_max: 30,
    },
    kpi_thresholds: {
      service_factor_min: 0.9,
      saturation_share_max: 0.05,
      oscillation_index_max: 0.3,
      noise_ratio_max: 0.2,
    },
    diagnosis_rules: ["instrument", "valve", "tuning"],
    tuning: { rule: "simc", target_closed_loop_time_constant_ratio: 1, robustness: 0.3 },
    tests: { allowed: ["step"], default_step_pct: 5 },
    origin: "builtin",
    ...overrides,
  };
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(async () => json(200, { templates: [makeTemplate()] }));
  vi.stubGlobal("fetch", fetchMock);
  setCsrfToken("csrf-1");
});

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

function lastCall(): { url: string; init: RequestInit } {
  const [url, init] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1] as [string, RequestInit];
  return { url, init };
}

describe("templateBody", () => {
  it("removes the read-only origin before a save", () => {
    expect(templateBody(makeTemplate())).not.toHaveProperty("origin");
  });
});

describe("reads", () => {
  it("lists with GET and without the CSRF header", async () => {
    const templates = await listLoopTemplates();
    expect(templates).toHaveLength(1);
    const { url, init } = lastCall();
    expect(url).toBe("/api/loop-templates");
    expect(init.method ?? "GET").toBe("GET");
    expect(init.headers).toBeUndefined();
  });
});

describe("writes", () => {
  it("saves with PUT, a JSON body without origin and the CSRF header", async () => {
    fetchMock.mockResolvedValue(json(200, makeTemplate({ origin: "site", label: "Site flow" })));
    const saved = await saveLoopTemplate("flow", makeTemplate({ label: "Site flow" }));
    const { url, init } = lastCall();
    expect(url).toBe("/api/loop-templates/flow");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(String(init.body))).toMatchObject({ key: "flow", label: "Site flow" });
    expect(JSON.parse(String(init.body))).not.toHaveProperty("origin");
    expect(init.headers).toMatchObject({
      "Content-Type": "application/json",
      "X-Crosscut-CSRF": "csrf-1",
    });
    expect(saved.origin).toBe("site");
  });

  it("carries status and detail lines of a refusal", async () => {
    fetchMock.mockResolvedValue(json(422, { detail: ["tuning: 'ziegler' is not valid"] }));
    const error = await saveLoopTemplate("flow", makeTemplate()).catch((one: unknown) => one);
    expect(error).toBeInstanceOf(LoopTemplateApiError);
    expect(error).toMatchObject({ status: 422, problems: ["tuning: 'ziegler' is not valid"] });
  });
});

describe("formatting", () => {
  it("shows the dynamics ranges with their units", () => {
    expect(formatDynamics(makeTemplate())).toBe("K 0.5–5, T 5–120 s, L 1–30 s");
  });

  it("shows the tuning rule and closed-loop target", () => {
    expect(formatTuning(makeTemplate())).toBe("SIMC, τcl/L 1");
  });
});

describe("invalidRangeFields", () => {
  it("accepts a consistent template", () => {
    expect(invalidRangeFields(makeTemplate())).toEqual([]);
  });

  it("flags a gain whose minimum is above its maximum", () => {
    const template = makeTemplate({
      dynamics: { ...makeTemplate().dynamics, gain_min: 10 },
    });
    expect(invalidRangeFields(template)).toContain("dynamics.gain");
  });

  it("flags a default step above the output span", () => {
    const template = makeTemplate({ tests: { allowed: ["step"], default_step_pct: 120 } });
    expect(invalidRangeFields(template)).toContain("tests.defaultStep");
  });
});

describe("toggleValue", () => {
  it("adds a missing value and removes a present one", () => {
    expect(toggleValue(["a"], "b")).toEqual(["a", "b"]);
    expect(toggleValue(["a", "b"], "b")).toEqual(["a"]);
  });
});

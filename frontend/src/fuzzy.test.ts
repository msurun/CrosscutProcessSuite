import { describe, expect, it } from "vitest";
import {
  SHAPE_PARAMETER_COUNTS,
  membership,
  newRuleId,
  sampleTerm,
  slugify,
  termColor,
  type FuzzyRule,
  type FuzzyTerm,
} from "./fuzzy";

/** Build a rule with the smallest shape the identifier helpers care about. */
function makeRule(id: string): FuzzyRule {
  return { id, if: [], then: { variable: "y", is: "x" } };
}

describe("membership for a triangle", () => {
  const triangle: FuzzyTerm = { name: "tri", shape: "tri", params: [0, 5, 10] };

  it("is 0 at the left foot", () => {
    expect(membership(triangle, 0)).toBe(0);
  });

  it("is 0 at the right foot", () => {
    expect(membership(triangle, 10)).toBe(0);
  });

  it("is 1 at the peak", () => {
    expect(membership(triangle, 5)).toBe(1);
  });

  it("is 0.5 halfway up the left slope", () => {
    expect(membership(triangle, 2.5)).toBe(0.5);
  });

  it("is 0.5 halfway down the right slope", () => {
    expect(membership(triangle, 7.5)).toBe(0.5);
  });

  it("is 0 outside the support on the left", () => {
    expect(membership(triangle, -1)).toBe(0);
  });

  it("is 0 outside the support on the right", () => {
    expect(membership(triangle, 11)).toBe(0);
  });
});

describe("membership for a trapezoid", () => {
  const trapezoid: FuzzyTerm = { name: "trap", shape: "trap", params: [0, 2, 4, 6] };

  it("is 1 on the whole plateau", () => {
    expect(membership(trapezoid, 3)).toBe(1);
  });

  it("is 1 at the left plateau corner", () => {
    expect(membership(trapezoid, 2)).toBe(1);
  });

  it("is 1 at the right plateau corner", () => {
    expect(membership(trapezoid, 4)).toBe(1);
  });

  it("is 0.5 halfway up the left slope", () => {
    expect(membership(trapezoid, 1)).toBe(0.5);
  });

  it("is 0.5 halfway down the right slope", () => {
    expect(membership(trapezoid, 5)).toBe(0.5);
  });
});

describe("membership for shoulder shapes", () => {
  it("a left shoulder triangle is 1 at the open end", () => {
    const leftShoulder: FuzzyTerm = { name: "low", shape: "tri", params: [0, 0, 5] };
    expect(membership(leftShoulder, 0)).toBe(1);
  });

  it("a left shoulder triangle falls to 0.5 at its midpoint", () => {
    const leftShoulder: FuzzyTerm = { name: "low", shape: "tri", params: [0, 0, 5] };
    expect(membership(leftShoulder, 2.5)).toBe(0.5);
  });

  it("a right shoulder trapezoid is 1 at the open end", () => {
    const rightShoulder: FuzzyTerm = { name: "high", shape: "trap", params: [5, 8, 10, 10] };
    expect(membership(rightShoulder, 10)).toBe(1);
  });

  it("a right shoulder trapezoid rises to 0.5 at its midpoint", () => {
    const rightShoulder: FuzzyTerm = { name: "high", shape: "trap", params: [5, 8, 10, 10] };
    expect(membership(rightShoulder, 6.5)).toBe(0.5);
  });
});

describe("membership for a gaussian", () => {
  const gaussian: FuzzyTerm = { name: "mid", shape: "gauss", params: [5, 2] };

  it("is 1 at the centre", () => {
    expect(membership(gaussian, 5)).toBe(1);
  });

  it("is exp(-0.5) one sigma away from the centre", () => {
    expect(membership(gaussian, 7)).toBeCloseTo(Math.exp(-0.5));
  });
});

describe("sampleTerm", () => {
  const triangle: FuzzyTerm = { name: "tri", shape: "tri", params: [0, 5, 10] };

  it("returns the requested number of points", () => {
    expect(sampleTerm(triangle, 0, 10, 51).x).toHaveLength(51);
  });

  it("spans from low to high", () => {
    const samples = sampleTerm(triangle, 0, 10, 51);
    expect(samples.x[0]).toBe(0);
    expect(samples.x[samples.x.length - 1]).toBe(10);
  });

  it("returns one y value per x value", () => {
    const samples = sampleTerm(triangle, 0, 10, 51);
    expect(samples.y).toHaveLength(samples.x.length);
  });

  it("matches membership at every sample", () => {
    const samples = sampleTerm(triangle, 0, 10, 51);
    const expected = samples.x.map((x) => membership(triangle, x));
    expect(samples.y).toEqual(expected);
  });

  it("uses 121 points by default", () => {
    expect(sampleTerm(triangle, 0, 10).x).toHaveLength(121);
  });
});

describe("termColor", () => {
  it("starts the palette at series 1", () => {
    expect(termColor(0)).toBe("--series-1");
  });

  it("wraps back to series 1 after the palette ends", () => {
    expect(termColor(7)).toBe("--series-1");
  });

  it("counts through the palette in order", () => {
    expect(termColor(2)).toBe("--series-3");
  });
});

describe("newRuleId", () => {
  it("names the first rule r1", () => {
    expect(newRuleId([])).toBe("r1");
  });

  it("continues after two existing rules", () => {
    expect(newRuleId([makeRule("r1"), makeRule("r2")])).toBe("r3");
  });

  it("skips an id that is already taken", () => {
    expect(newRuleId([makeRule("r2"), makeRule("r3")])).toBe("r4");
  });
});

describe("slugify", () => {
  it("lowercases and joins words with underscores", () => {
    expect(slugify("My Mill Feed!")).toBe("my_mill_feed");
  });

  it("falls back to my_system for a blank name", () => {
    expect(slugify("  ")).toBe("my_system");
  });

  it("truncates a long name to 64 characters", () => {
    expect(slugify("a".repeat(100))).toHaveLength(64);
  });

  it("replaces hyphens with underscores", () => {
    expect(slugify("a-b")).toBe("a_b");
  });
});

describe("SHAPE_PARAMETER_COUNTS", () => {
  it("lists the parameter count of every shape", () => {
    expect(SHAPE_PARAMETER_COUNTS).toEqual({ tri: 3, trap: 4, gauss: 2 });
  });
});

// src/benefitInputs.test.ts
// Tests the pure conversion from the benefit form's text fields to the API request.
// The before/after retune deviations are sent only as a complete, valid pair, because the server
// switches to the measured cut only when it receives both values.
import { describe, expect, it, vi } from "vitest";
import { toRequestInputs, type BenefitInputStrings } from "./components/BenefitPage";

// The chart pulls in uPlot, which needs window.matchMedia; the conversion does not draw anything.
vi.mock("./components/TrendPane", () => ({ TrendPane: () => null }));

/** Form values with every field empty, overridden by the fields a test cares about. */
function formWith(overrides: Partial<BenefitInputStrings>): BenefitInputStrings {
  return {
    limit: "",
    side: "upper",
    value: "",
    margin: "",
    reduction: "",
    stdBefore: "",
    stdAfter: "",
    ...overrides,
  };
}

describe("toRequestInputs retune pair", () => {
  it("sends no retune deviations when both fields are empty", () => {
    const request = toRequestInputs(formWith({}));

    expect(request.stdBefore).toBeUndefined();
    expect(request.stdAfter).toBeUndefined();
  });

  it("sends no retune deviations when only the before field is filled", () => {
    const request = toRequestInputs(formWith({ stdBefore: "2" }));

    expect(request.stdBefore).toBeUndefined();
    expect(request.stdAfter).toBeUndefined();
  });

  it("sends no retune deviations when only the after field is filled", () => {
    const request = toRequestInputs(formWith({ stdAfter: "1" }));

    expect(request.stdBefore).toBeUndefined();
    expect(request.stdAfter).toBeUndefined();
  });

  it("sends both deviations when before is 2 and after is 1", () => {
    const request = toRequestInputs(formWith({ stdBefore: "2", stdAfter: "1" }));

    expect(request.stdBefore).toBe(2);
    expect(request.stdAfter).toBe(1);
  });

  it("sends an after value of zero when the variability was fully removed", () => {
    const request = toRequestInputs(formWith({ stdBefore: "2", stdAfter: "0" }));

    expect(request.stdBefore).toBe(2);
    expect(request.stdAfter).toBe(0);
  });

  it("sends no retune deviations when before is zero", () => {
    const request = toRequestInputs(formWith({ stdBefore: "0", stdAfter: "1" }));

    expect(request.stdBefore).toBeUndefined();
    expect(request.stdAfter).toBeUndefined();
  });

  it("sends no retune deviations when a field is not a number", () => {
    const request = toRequestInputs(formWith({ stdBefore: "abc", stdAfter: "1" }));

    expect(request.stdBefore).toBeUndefined();
    expect(request.stdAfter).toBeUndefined();
  });
});

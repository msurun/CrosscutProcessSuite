// Tests for CurrentSettingsCompare: pure helpers, input validation, the
// comparison table, the closeness status and the localStorage round-trip.

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  CurrentSettingsCompare,
  formatChange,
  parsePositive,
  relativeChange,
} from "./CurrentSettingsCompare";

const STORAGE_KEY = "current-settings-test";

/** Fake translator: returns the key, plus any params as JSON, so tests can see both. */
const t = (key: string, params?: Record<string, unknown>): string =>
  key + (params ? JSON.stringify(params) : "");

/** Proposed settings used across the tests (Kc gain, Ti in seconds). */
const settings = {
  simc: { kc: 10, ti_s: 20 },
  amigo: { kc: 8, ti_s: 16 },
};

/** Render the component and return the Kc and Ti text inputs. */
function renderAndGetInputs() {
  render(<CurrentSettingsCompare storageKey={STORAGE_KEY} settings={settings} t={t} />);
  const [kcInput, tiInput] = screen.getAllByRole("textbox");
  return { kcInput, tiInput };
}

/** Type a current Kc and Ti, both valid. */
function fillValidValues(kc: string, ti: string): void {
  const { kcInput, tiInput } = renderAndGetInputs();
  fireEvent.change(kcInput, { target: { value: kc } });
  fireEvent.change(tiInput, { target: { value: ti } });
}

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("relativeChange", () => {
  it("returns a positive percentage when the proposed value is larger", () => {
    expect(relativeChange(8, 10)).toBeCloseTo(25);
  });

  it("returns a negative percentage when the proposed value is smaller", () => {
    expect(relativeChange(10, 8)).toBeCloseTo(-20);
  });

  it("returns zero when the proposed value equals the current one", () => {
    expect(relativeChange(20, 20)).toBe(0);
  });
});

describe("parsePositive", () => {
  it("accepts a decimal comma as a separator", () => {
    expect(parsePositive("3,5")).toBe(3.5);
  });

  it("returns null for blank text", () => {
    expect(parsePositive("   ")).toBeNull();
  });

  it("returns null for zero", () => {
    expect(parsePositive("0")).toBeNull();
  });

  it("returns null for a negative number", () => {
    expect(parsePositive("-2")).toBeNull();
  });

  it("returns null for text that is not a number", () => {
    expect(parsePositive("abc")).toBeNull();
  });

  it("returns null for Infinity", () => {
    expect(parsePositive("Infinity")).toBeNull();
  });
});

describe("formatChange", () => {
  it("adds a plus sign and one decimal to a positive change", () => {
    expect(formatChange(25)).toBe("+25.0 %");
  });

  it("shows a zero change without a sign", () => {
    expect(formatChange(0)).toBe("0.0 %");
  });
});

describe("CurrentSettingsCompare", () => {
  it("shows no table and no status until both fields hold valid values", () => {
    const { kcInput } = renderAndGetInputs();
    fireEvent.change(kcInput, { target: { value: "8" } });

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("shows a SIMC and an AMIGO row with signed percentages once both fields are valid", () => {
    fillValidValues("8", "20");

    expect(screen.getByRole("rowheader", { name: "AMIGO" })).toBeInTheDocument();
    const simcRow = screen.getByRole("rowheader", { name: "SIMC" }).closest("tr");
    expect(simcRow).toHaveTextContent("+25.0 %");
    expect(simcRow).toHaveTextContent("0.0 %");
  });

  it("reports the values as close when both SIMC changes stay within 10 %", () => {
    fillValidValues("10", "20");

    expect(screen.getByRole("status")).toHaveTextContent("tuning.current.close");
  });

  it("reports the values as different when a SIMC change exceeds 10 %", () => {
    fillValidValues("8", "20");

    expect(screen.getByRole("status")).toHaveTextContent("tuning.current.differs");
  });

  it("shows an alert and marks the field invalid when the text is not a positive number", () => {
    const { kcInput } = renderAndGetInputs();
    fireEvent.change(kcInput, { target: { value: "-1" } });

    expect(kcInput).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toHaveTextContent("tuning.current.invalid");
  });

  it("stores both values in localStorage under the given key", () => {
    fillValidValues("8", "20");

    expect(JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null")).toEqual({ kc: 8, ti: 20 });
  });

  it("restores stored values on a fresh mount", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ kc: 8, ti: 20 }));

    renderAndGetInputs();

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("tuning.current.differs");
  });

  it("still compares values when reading from localStorage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage blocked");
    });

    fillValidValues("8", "20");

    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("still compares values when writing to localStorage throws", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage full");
    });

    fillValidValues("8", "20");

    expect(screen.getByRole("status")).toHaveTextContent("tuning.current.differs");
  });
});

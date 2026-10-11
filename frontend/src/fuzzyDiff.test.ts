/** Behaviour of the fuzzy rule base diff helpers. */

import { describe, expect, it } from "vitest";

import type { FuzzyChange } from "./api";
import type { Translate } from "./findings";
import { changeText, versionLabel } from "./fuzzyDiff";

/** Translator that echoes the key and its parameters, so tests can assert on both. */
const t: Translate = (key, params) => key + JSON.stringify(params ?? {});

/** Rebuild the expected sentence with the same translator, keeping the assertion readable. */
function expected(key: string, params: Record<string, string | number>): string {
  return t(key, params);
}

describe("versionLabel", () => {
  it("formats a valid version id as a UTC timestamp", () => {
    expect(versionLabel("20261011T101500123456Z")).toBe("2026-10-11 10:15:00 UTC");
  });

  it("returns an id that does not match the pattern unchanged", () => {
    expect(versionLabel("latest")).toBe("latest");
  });
});

describe("changeText", () => {
  it("describes a variable_added change", () => {
    const change: FuzzyChange = { code: "variable_added", variable: "temperature" };

    expect(changeText(t, change)).toBe(
      expected("fuzzy.change.variable_added", {
        variable: "temperature",
        term: "",
        rule: "",
        old: "",
        new: "",
        fields: "",
      }),
    );
  });

  it("describes a variable_removed change", () => {
    const change: FuzzyChange = { code: "variable_removed", variable: "pressure" };

    expect(changeText(t, change)).toBe(
      expected("fuzzy.change.variable_removed", {
        variable: "pressure",
        term: "",
        rule: "",
        old: "",
        new: "",
        fields: "",
      }),
    );
  });

  it("shows both ranges of a range_changed change", () => {
    const change: FuzzyChange = { code: "range_changed", variable: "temperature", old: [0, 100], new: [0, 120] };

    expect(changeText(t, change)).toBe(
      expected("fuzzy.change.range_changed", {
        variable: "temperature",
        term: "",
        rule: "",
        old: "0..100",
        new: "0..120",
        fields: "",
      }),
    );
  });

  it("describes a term_added change", () => {
    const change: FuzzyChange = { code: "term_added", variable: "temperature", term: "warm" };

    expect(changeText(t, change)).toBe(
      expected("fuzzy.change.term_added", {
        variable: "temperature",
        term: "warm",
        rule: "",
        old: "",
        new: "",
        fields: "",
      }),
    );
  });

  it("describes a term_removed change", () => {
    const change: FuzzyChange = { code: "term_removed", variable: "temperature", term: "cold" };

    expect(changeText(t, change)).toBe(
      expected("fuzzy.change.term_removed", {
        variable: "temperature",
        term: "cold",
        rule: "",
        old: "",
        new: "",
        fields: "",
      }),
    );
  });

  it("shows both terms of a term_changed change in tri(a, b, c) form", () => {
    const change: FuzzyChange = {
      code: "term_changed",
      variable: "temperature",
      term: "warm",
      old: { shape: "tri", params: [0, 5, 10] },
      new: { shape: "tri", params: [2, 6, 10] },
    };

    expect(changeText(t, change)).toBe(
      expected("fuzzy.change.term_changed", {
        variable: "temperature",
        term: "warm",
        rule: "",
        old: "tri(0, 5, 10)",
        new: "tri(2, 6, 10)",
        fields: "",
      }),
    );
  });

  it("describes a rule_added change", () => {
    const change: FuzzyChange = { code: "rule_added", rule: "r1" };

    expect(changeText(t, change)).toBe(
      expected("fuzzy.change.rule_added", {
        variable: "",
        term: "",
        rule: "r1",
        old: "",
        new: "",
        fields: "",
      }),
    );
  });

  it("describes a rule_removed change", () => {
    const change: FuzzyChange = { code: "rule_removed", rule: "r2" };

    expect(changeText(t, change)).toBe(
      expected("fuzzy.change.rule_removed", {
        variable: "",
        term: "",
        rule: "r2",
        old: "",
        new: "",
        fields: "",
      }),
    );
  });

  it("lists the changed fields of a rule_changed change", () => {
    const change: FuzzyChange = { code: "rule_changed", rule: "r3", fields: ["if", "weight"] };

    expect(changeText(t, change)).toBe(
      expected("fuzzy.change.rule_changed", {
        variable: "",
        term: "",
        rule: "r3",
        old: "",
        new: "",
        fields: "if, weight",
      }),
    );
  });
});

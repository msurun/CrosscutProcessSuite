// Tests of the pure rule-matrix edits: default axes, reading a cell, and setting, changing or
// removing the rule of a cell. The matrix object is what POST /fuzzy/matrix answers.
import { describe, expect, it } from "vitest";
import type { FuzzyMatrix } from "./api";
import type { FuzzyDocument } from "./fuzzy";
import { cellTerm, defaultAxes, setMatrixCell } from "./fuzzyMatrix";

const term = (name: string) => ({ name, shape: "tri" as const, params: [0, 1, 2] });
const variable = (id: string, names: string[]) => ({ id, low: 0, high: 10, terms: names.map(term) });

const DOC: FuzzyDocument = {
  schema_version: "1",
  name: "d",
  inputs: [variable("load", ["low", "high"]), variable("power", ["low", "high"])],
  outputs: [variable("feed", ["up", "down"])],
  rules: [{ id: "r1", if: [{ variable: "load", is: "low" }, { variable: "power", is: "low" }], operator: "and", then: { variable: "feed", is: "up" } }],
};

const ENTRY = { rule_id: "r1", output_term: "up", weight: 1, enabled: true };
const MATRIX: FuzzyMatrix = {
  row_variable: "load", column_variable: "power", output: "feed",
  rows: ["low", "high"], columns: ["low", "high"],
  cells: [[[ENTRY], []], [[], []]],
  unplaced: [],
};
const TWO: FuzzyMatrix = { ...MATRIX, cells: [[[ENTRY, { ...ENTRY, rule_id: "r2" }], []], [[], []]] };

describe("defaultAxes", () => {
  it("takes the first two inputs and the first output", () => {
    expect(defaultAxes(DOC)).toEqual({ rowId: "load", columnId: "power", outputId: "feed" });
  });
  it("is null with fewer than two inputs", () => {
    expect(defaultAxes({ ...DOC, inputs: DOC.inputs.slice(0, 1) })).toBeNull();
  });
});

describe("cellTerm", () => {
  it("is the term, empty, or null for several rules", () => {
    expect(cellTerm(MATRIX, 0, 0)).toBe("up");
    expect(cellTerm(MATRIX, 1, 1)).toBe("");
    expect(cellTerm(TWO, 0, 0)).toBeNull();
  });
});

describe("setMatrixCell", () => {
  it("adds an AND rule with a fresh id to an empty cell", () => {
    const next = setMatrixCell(DOC, MATRIX, 1, 0, "down");
    expect(next.rules).toHaveLength(2);
    expect(next.rules[1]).toMatchObject({ id: "r2", operator: "and", then: { variable: "feed", is: "down" } });
    expect(next.rules[1].if).toEqual([{ variable: "load", is: "high" }, { variable: "power", is: "low" }]);
    expect(DOC.rules).toHaveLength(1);
  });
  it("changes the conclusion of the existing rule", () => {
    const next = setMatrixCell(DOC, MATRIX, 0, 0, "down");
    expect(next.rules).toHaveLength(1);
    expect(next.rules[0].then.is).toBe("down");
  });
  it("removes the rule when the term is empty", () => {
    expect(setMatrixCell(DOC, MATRIX, 0, 0, "").rules).toEqual([]);
  });
  it("leaves an empty cell and a multi-rule cell alone", () => {
    expect(setMatrixCell(DOC, MATRIX, 1, 1, "")).toBe(DOC);
    expect(setMatrixCell(DOC, TWO, 0, 0, "down")).toBe(DOC);
  });
});

// Component tests of the Fuzzy Studio Matrix tab: the grid from POST /fuzzy/matrix, editing a
// cell hands a new document to onChange, the unplaced-rule note and the error and too-few-inputs states.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { FuzzyMatrix } from "../api";
import type { FuzzyDocument } from "../fuzzy";
import { translate } from "../i18n";
import { MatrixPanel } from "./MatrixPanel";

const t = (key: string, params?: Record<string, string | number>) => translate("en", key, params);
const term = (name: string) => ({ name, shape: "tri" as const, params: [0, 1, 2] });
const variable = (id: string, names: string[]) => ({ id, low: 0, high: 10, terms: names.map(term) });

const DOC: FuzzyDocument = {
  schema_version: "1", name: "d",
  inputs: [variable("load", ["low", "high"]), variable("power", ["low", "high"])],
  outputs: [variable("feed", ["up", "down"])],
  rules: [{ id: "r1", if: [{ variable: "load", is: "low" }, { variable: "power", is: "low" }], operator: "and", then: { variable: "feed", is: "up" } }],
};

const MATRIX: FuzzyMatrix = {
  row_variable: "load", column_variable: "power", output: "feed",
  rows: ["low", "high"], columns: ["low", "high"],
  cells: [[[{ rule_id: "r1", output_term: "up", weight: 1, enabled: true }], []], [[], []]],
  unplaced: ["r9"],
};

function stub(status = 200, body: unknown = MATRIX) {
  const mock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(body), { status })));
  vi.stubGlobal("fetch", mock);
  return mock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("MatrixPanel", () => {
  it("asks the server for the matrix of the default axes and draws the grid", async () => {
    const mock = stub();
    render(<MatrixPanel document={DOC} onChange={vi.fn()} t={t} />);
    const select = await screen.findByLabelText("Output term when row is low and column is low");
    expect(select).toHaveValue("up");
    const sent = JSON.parse((mock.mock.calls[0][1] as { body: string }).body);
    expect(sent).toMatchObject({ row_id: "load", column_id: "power", output_id: "feed" });
    expect(screen.getByTestId("matrix-unplaced")).toHaveTextContent("1 rules do not fit this grid: r9");
  });

  it("hands a new document to onChange when a cell is chosen", async () => {
    stub();
    const onChange = vi.fn();
    render(<MatrixPanel document={DOC} onChange={onChange} t={t} />);
    fireEvent.change(await screen.findByLabelText("Output term when row is high and column is high"), { target: { value: "down" } });
    const next = onChange.mock.calls[0][0] as FuzzyDocument;
    expect(next.rules).toHaveLength(2);
    expect(next.rules[1].then.is).toBe("down");
  });

  it("shows the server's reason on a 422", async () => {
    stub(422, { detail: "row and column variable are the same: load" });
    render(<MatrixPanel document={DOC} onChange={vi.fn()} t={t} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("row and column variable are the same");
  });

  it("explains the minimum without calling the server when there are fewer than two inputs", () => {
    const mock = stub();
    render(<MatrixPanel document={{ ...DOC, inputs: DOC.inputs.slice(0, 1) }} onChange={vi.fn()} t={t} />);
    expect(screen.getByText("The matrix needs at least two inputs and one output.")).toBeInTheDocument();
    expect(mock).not.toHaveBeenCalled();
  });

  it("refetches when another input is chosen for the rows", async () => {
    const mock = stub();
    render(<MatrixPanel document={DOC} onChange={vi.fn()} t={t} />);
    await screen.findByLabelText("Output term when row is low and column is low");
    fireEvent.change(screen.getByLabelText("Rows (input)"), { target: { value: "power" } });
    await waitFor(() => expect(mock).toHaveBeenCalledTimes(2));
  });
});

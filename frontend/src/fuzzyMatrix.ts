// Pure edit of one cell of the fuzzy rule matrix: the grid comes from POST /fuzzy/matrix, the
// change goes back into the document as a new rule, a changed conclusion or a removed rule.
import { newRuleId, type FuzzyDocument, type FuzzyRule } from "./fuzzy";
import type { FuzzyMatrix } from "./api";

/** The input pair (rows, columns) and output the matrix shows. */
export interface MatrixAxes {
  rowId: string;
  columnId: string;
  outputId: string;
}

/** Default axes: the first two inputs and the first output; null when the base has fewer. */
export function defaultAxes(document: FuzzyDocument): MatrixAxes | null {
  if (document.inputs.length < 2 || document.outputs.length < 1) return null;
  return { rowId: document.inputs[0].id, columnId: document.inputs[1].id, outputId: document.outputs[0].id };
}

/** The output term of a cell that holds exactly one rule, "" when it is empty, null when several. */
export function cellTerm(matrix: FuzzyMatrix, row: number, column: number): string | null {
  const entries = matrix.cells[row][column];
  if (entries.length === 0) return "";
  return entries.length === 1 ? entries[0].output_term : null;
}

function newCellRule(document: FuzzyDocument, matrix: FuzzyMatrix, row: number, column: number, term: string): FuzzyRule {
  return {
    id: newRuleId(document.rules),
    if: [
      { variable: matrix.row_variable, is: matrix.rows[row] },
      { variable: matrix.column_variable, is: matrix.columns[column] },
    ],
    operator: "and",
    then: { variable: matrix.output, is: term },
    weight: 1,
    enabled: true,
  };
}

/**
 * A new document with the cell set to `term` ("" removes the rule). A cell with several rules is
 * left alone (the grid shows it read-only), so the document is returned unchanged.
 */
export function setMatrixCell(document: FuzzyDocument, matrix: FuzzyMatrix, row: number, column: number, term: string): FuzzyDocument {
  const entries = matrix.cells[row][column];
  if (entries.length > 1) return document;
  if (entries.length === 0) {
    return term === "" ? document : { ...document, rules: [...document.rules, newCellRule(document, matrix, row, column, term)] };
  }
  const id = entries[0].rule_id;
  if (term === "") return { ...document, rules: document.rules.filter((rule) => rule.id !== id) };
  const rules = document.rules.map((rule) => (rule.id === id ? { ...rule, then: { ...rule.then, is: term } } : rule));
  return { ...document, rules };
}

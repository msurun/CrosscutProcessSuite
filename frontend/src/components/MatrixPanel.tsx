// Rule matrix tab of the Fuzzy Studio (PRODUCT.md 4.4): two inputs as rows and columns, the output
// term of the rule in each cell. The grid comes from POST /fuzzy/matrix; choosing a term in a cell
// edits the rule base (new rule, changed conclusion or removed rule) and the grid is fetched again.
import { useEffect, useState } from "react";
import { fetchFuzzyMatrix, type FuzzyMatrix } from "../api";
import type { Translate } from "../findings";
import type { FuzzyDocument } from "../fuzzy";
import { cellTerm, defaultAxes, setMatrixCell, type MatrixAxes } from "../fuzzyMatrix";
import { termLabel, variableLabel } from "../fuzzyNames";
import { describeError } from "./AdvisoryState";

interface VariableSelectProps {
  label: string;
  value: string;
  variables: FuzzyDocument["inputs"];
  onChange: (id: string) => void;
  t: Translate;
}

function VariableSelect({ label, value, variables, onChange, t }: VariableSelectProps) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <select className="field-input" value={value} onChange={(event) => onChange(event.target.value)}>
        {variables.map((variable) => <option key={variable.id} value={variable.id}>{variableLabel(t, variable)}</option>)}
      </select>
    </label>
  );
}

interface GridProps {
  matrix: FuzzyMatrix;
  document: FuzzyDocument;
  onChange: (document: FuzzyDocument) => void;
  t: Translate;
}

/** One cell: a select of the output terms, or the rule list when the cell holds several rules. */
function Cell({ matrix, document, onChange, row, column, t }: GridProps & { row: number; column: number }) {
  const entries = matrix.cells[row][column];
  const term = cellTerm(matrix, row, column);
  const output = document.outputs.find((variable) => variable.id === matrix.output);
  if (term === null) {
    return <td data-testid="matrix-cell-multi">{entries.map((entry) => `${entry.rule_id}: ${termLabel(t, matrix.output, entry.output_term)}`).join("; ")}</td>;
  }
  const name = t("fuzzy.matrix.cell", { row: matrix.rows[row], column: matrix.columns[column] });
  return (
    <td>
      <select
        aria-label={name}
        value={term}
        onChange={(event) => onChange(setMatrixCell(document, matrix, row, column, event.target.value))}
      >
        <option value="">{t("fuzzy.matrix.none")}</option>
        {output?.terms.map((candidate) => <option key={candidate.name} value={candidate.name}>{termLabel(t, matrix.output, candidate.name)}</option>)}
      </select>
    </td>
  );
}

/** The grid: column terms across, row terms down. */
function Grid(props: GridProps) {
  const { matrix, t } = props;
  return (
    <div className="table-scroll">
      <table className="settings-table" aria-label={t("fuzzy.matrix.title")}>
        <thead>
          <tr>
            <th scope="col">{matrix.row_variable} \ {matrix.column_variable}</th>
            {matrix.columns.map((name) => <th key={name} scope="col">{termLabel(t, matrix.column_variable, name)}</th>)}
          </tr>
        </thead>
        <tbody>
          {matrix.rows.map((rowName, row) => (
            <tr key={rowName}>
              <th scope="row">{termLabel(t, matrix.row_variable, rowName)}</th>
              {matrix.columns.map((columnName, column) => <Cell key={columnName} {...props} row={row} column={column} />)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Fetches the matrix whenever the document or the axes change. */
function useMatrix(document: FuzzyDocument, axes: MatrixAxes | null) {
  const [matrix, setMatrix] = useState<FuzzyMatrix | null>(null);
  const [error, setError] = useState<string | null>(null);
  const rowId = axes?.rowId;
  const columnId = axes?.columnId;
  const outputId = axes?.outputId;
  useEffect(() => {
    if (rowId === undefined || columnId === undefined || outputId === undefined) return;
    let current = true;
    fetchFuzzyMatrix(document, rowId, columnId, outputId)
      .then((grid) => { if (current) { setMatrix(grid); setError(null); } })
      .catch((failure: unknown) => { if (current) setError(describeError(failure)); });
    return () => { current = false; };
  }, [document, rowId, columnId, outputId]);
  return { matrix, error };
}

interface MatrixPanelProps {
  document: FuzzyDocument;
  onChange: (document: FuzzyDocument) => void;
  t: Translate;
}

/** The Matrix tab. Needs at least two inputs and one output. */
export function MatrixPanel({ document, onChange, t }: MatrixPanelProps) {
  const [chosen, setChosen] = useState<MatrixAxes | null>(null);
  const axes = chosen ?? defaultAxes(document);
  const { matrix, error } = useMatrix(document, axes);
  if (axes === null) return <p className="status">{t("fuzzy.matrix.needTwo")}</p>;
  const set = (patch: Partial<MatrixAxes>) => setChosen({ ...axes, ...patch });
  return (
    <section aria-label={t("fuzzy.matrix.title")}>
      <p className="hint">{t("fuzzy.matrix.hint")}</p>
      <div className="toolbar">
        <VariableSelect label={t("fuzzy.matrix.rows")} value={axes.rowId} variables={document.inputs} onChange={(rowId) => set({ rowId })} t={t} />
        <VariableSelect label={t("fuzzy.matrix.columns")} value={axes.columnId} variables={document.inputs} onChange={(columnId) => set({ columnId })} t={t} />
        <VariableSelect label={t("fuzzy.matrix.output")} value={axes.outputId} variables={document.outputs} onChange={(outputId) => set({ outputId })} t={t} />
      </div>
      {error !== null && <p className="status status-error" role="alert">{t("trends.error", { reason: error })}</p>}
      {matrix !== null && error === null && <Grid matrix={matrix} document={document} onChange={onChange} t={t} />}
      {matrix !== null && matrix.unplaced.length > 0 && (
        <p className="hint" data-testid="matrix-unplaced">{t("fuzzy.matrix.unplaced", { count: matrix.unplaced.length, rules: matrix.unplaced.join(", ") })}</p>
      )}
    </section>
  );
}

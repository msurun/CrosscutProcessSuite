/** Editor of the fuzzy variables of one kind: pick a variable, tune its terms, see the membership chart. */

import { useEffect, useState } from "react";
import type { FuzzyDocument, FuzzyTerm, FuzzyVariable, TermShape } from "../fuzzy";
import { SHAPE_PARAMETER_COUNTS } from "../fuzzy";
import type { Translate } from "../findings";
import { MembershipChart } from "./MembershipChart";

/** Parameter sets used when a term switches shape; each one fits inside [low, high]. */
const DEFAULT_PARAMS: Record<TermShape, (low: number, high: number) => number[]> = {
  tri: (low, high) => [low, (low + high) / 2, high],
  trap: (low, high) => [low, low + (high - low) / 3, low + (2 * (high - low)) / 3, high],
  gauss: (low, high) => [(low + high) / 2, (high - low) / 6],
};

const SHAPE_ORDER: TermShape[] = ["tri", "trap", "gauss"];

/** Options of the shape select, in the order they are shown. */
const SHAPE_LABEL_KEYS: Record<TermShape, string> = {
  tri: "fuzzy.term.shape.tri",
  trap: "fuzzy.term.shape.trap",
  gauss: "fuzzy.term.shape.gauss",
};

/** Props of {@link VariableEditor}. */
export interface VariableEditorProps {
  document: FuzzyDocument;
  kind: "inputs" | "outputs";
  onChange: (next: FuzzyDocument) => void;
  values?: Record<string, number>;
  degrees?: Record<string, Record<string, number>>;
  t: Translate;
}

/**
 * Edit the variables of one kind of a rule base.
 * Every change is reported through `onChange` as a brand new document; nothing is mutated.
 */
export function VariableEditor({ document, kind, onChange, values, degrees, t }: VariableEditorProps) {
  const variables = document[kind];
  const [selectedId, setSelectedId] = useState<string>(variables[0]?.id ?? "");
  const [selectedTerm, setSelectedTerm] = useState<string | null>(null);

  // Keep the selection valid when the list changes from the outside (load, delete, rename).
  useEffect(() => {
    if (!variables.some((variable) => variable.id === selectedId)) {
      setSelectedId(variables[0]?.id ?? "");
    }
  }, [variables, selectedId]);

  const selected = variables.find((variable) => variable.id === selectedId) ?? null;
  return (
    <section className="variable-editor">
      <h3>{t(kind === "inputs" ? "fuzzy.inputs" : "fuzzy.outputs")}</h3>
      <VariableChips variables={variables} selectedId={selectedId} onSelect={setSelectedId} />
      {selected !== null && (
        <SelectedVariable variable={selected} t={t} />
      )}
      {selected !== null && (
        <MembershipChart
          variable={selected}
          value={values?.[selected.id]}
          degrees={degrees?.[selected.id]}
          selectedTerm={selectedTerm}
          onSelectTerm={setSelectedTerm}
        />
      )}
      {selected?.tag !== undefined && <p className="hint">{t("fuzzy.variable.tag") + ": " + selected.tag}</p>}
      {selected !== null && (
        <TermTable
          variable={selected}
          selectedTerm={selectedTerm}
          onSelectTerm={setSelectedTerm}
          onChange={(nextVariable) => replaceVariable(document, kind, nextVariable, onChange)}
          t={t}
        />
      )}
    </section>
  );
}

/** One chip per variable; the pressed chip is the one being edited. */
function VariableChips({
  variables,
  selectedId,
  onSelect,
}: {
  variables: FuzzyVariable[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="chip-row">
      {variables.map((variable) => (
        <button
          key={variable.id}
          type="button"
          className="filter-chip"
          aria-pressed={variable.id === selectedId}
          onClick={() => onSelect(variable.id)}
        >
          {variable.label ?? variable.id}
        </button>
      ))}
    </div>
  );
}

/** Range line of the selected variable: "low … high unit", plus its tag when it has one. */
function SelectedVariable({ variable, t }: { variable: FuzzyVariable; t: Translate }) {
  const range = t("fuzzy.variable.range", {
    low: variable.low,
    high: variable.high,
    unit: variable.unit ?? "",
  });
  return <p className="hint">{range}</p>;
}

/** Table of terms: name, shape select and one number input per parameter. */
function TermTable({
  variable,
  selectedTerm,
  onSelectTerm,
  onChange,
  t,
}: {
  variable: FuzzyVariable;
  selectedTerm: string | null;
  onSelectTerm: (name: string) => void;
  onChange: (next: FuzzyVariable) => void;
  t: Translate;
}) {
  return (
    <table className="settings-table">
      <tbody>
        {variable.terms.map((term) => (
          <TermRow
            key={term.name}
            term={term}
            variable={variable}
            isSelected={term.name === selectedTerm}
            onSelect={() => onSelectTerm(term.name)}
            onChange={(nextTerm) => onChange(replaceTerm(variable, nextTerm))}
            t={t}
          />
        ))}
      </tbody>
    </table>
  );
}

/** One term row; clicking it selects the term, editing it rewrites the variable. */
function TermRow({
  term,
  variable,
  isSelected,
  onSelect,
  onChange,
  t,
}: {
  term: FuzzyTerm;
  variable: FuzzyVariable;
  isSelected: boolean;
  onSelect: () => void;
  onChange: (next: FuzzyTerm) => void;
  t: Translate;
}) {
  return (
    <tr className={isSelected ? "row-selected" : undefined} onClick={onSelect}>
      <td>{term.name}</td>
      <td>
        <ShapeSelect shape={term.shape} onChange={(shape) => onChange(changeShape(term, shape, variable))} t={t} />
      </td>
      {term.params.map((value, index) => (
        <td key={index}>
          <input
            type="number"
            step="any"
            value={value}
            onChange={(event) => {
              const next = replaceParameter(term, index, event.target.value);
              if (next !== null) onChange(next);
            }}
          />
        </td>
      ))}
      <td>{isTermInvalid(term) && <span className="status status-error">{t("fuzzy.term.invalid")}</span>}</td>
    </tr>
  );
}

/** Dropdown of the three shapes. */
function ShapeSelect({ shape, onChange, t }: { shape: TermShape; onChange: (shape: TermShape) => void; t: Translate }) {
  return (
    <select value={shape} onChange={(event) => onChange(event.target.value as TermShape)}>
      {SHAPE_ORDER.map((candidate) => (
        <option key={candidate} value={candidate}>
          {t(SHAPE_LABEL_KEYS[candidate])}
        </option>
      ))}
    </select>
  );
}

/**
 * True when the parameters cannot describe a membership function.
 * Triangular and trapezoidal terms need non-decreasing corners that span a range; a gaussian needs a positive sigma.
 */
export function isTermInvalid(term: FuzzyTerm): boolean {
  if (term.params.length !== SHAPE_PARAMETER_COUNTS[term.shape]) return true;
  if (term.shape === "gauss") return term.params[1] <= 0;
  const isNonDecreasing = term.params.every((value, index) => index === 0 || value >= term.params[index - 1]);
  return !isNonDecreasing || term.params[0] === term.params[term.params.length - 1];
}

/** Copy of `term` with another shape and the default parameters of that shape. */
function changeShape(term: FuzzyTerm, shape: TermShape, variable: FuzzyVariable): FuzzyTerm {
  return { ...term, shape, params: DEFAULT_PARAMS[shape](variable.low, variable.high) };
}

/** Copy of `term` with parameter `index` set to `text`, or null when the text is not a finite number. */
function replaceParameter(term: FuzzyTerm, index: number, text: string): FuzzyTerm | null {
  const value = Number(text);
  if (!Number.isFinite(value)) return null;
  const params = term.params.map((current, position) => (position === index ? value : current));
  return { ...term, params };
}

/** Copy of `variable` with `term` in place of the term of the same name. */
function replaceTerm(variable: FuzzyVariable, term: FuzzyTerm): FuzzyVariable {
  const terms = variable.terms.map((current) => (current.name === term.name ? term : current));
  return { ...variable, terms };
}

/** Copy of `document` where the changed variable replaces the one of the same id. */
function replaceVariable(
  document: FuzzyDocument,
  kind: "inputs" | "outputs",
  variable: FuzzyVariable,
  onChange: (next: FuzzyDocument) => void,
): void {
  const replaced = document[kind].map((current) => (current.id === variable.id ? variable : current));
  onChange({ ...document, [kind]: replaced });
}

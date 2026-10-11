/**
 * Editor for the fuzzy rule base of a {@link FuzzyDocument}.
 *
 * Every edit produces a new document and hands it to `onChange`; the component
 * never mutates the document it receives.
 */

import type { FuzzyClause, FuzzyDocument, FuzzyRule } from "../fuzzy";
import { newRuleId } from "../fuzzy";
import type { Translate } from "../findings";

/** First term name of a variable, used when a condition has to be reset. */
function firstTermName(document: FuzzyDocument, variableId: string): string {
  const variable = [...document.inputs, ...document.outputs].find((candidate) => candidate.id === variableId);
  if (variable === undefined || variable.terms.length === 0) {
    throw new Error(`Variable "${variableId}" has no term to select.`);
  }
  return variable.terms[0].name;
}

/** A condition on the first input and its first term; needs at least one input. */
function defaultCondition(document: FuzzyDocument): FuzzyClause {
  if (document.inputs.length === 0) {
    throw new Error("A rule needs at least one input variable.");
  }
  const input = document.inputs[0];
  return { variable: input.id, is: firstTermName(document, input.id) };
}

/** A conclusion on the first output and its first term; needs at least one output. */
function defaultConclusion(document: FuzzyDocument): FuzzyClause {
  if (document.outputs.length === 0) {
    throw new Error("A rule needs at least one output variable.");
  }
  const output = document.outputs[0];
  return { variable: output.id, is: firstTermName(document, output.id) };
}

/** Clamp a possibly invalid weight into 0..1; non-finite input falls back to `fallback`. */
function clampWeight(raw: string, fallback: number): number {
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(1, Math.max(0, parsed));
}

/** Options of a `<select>` listing variables by id, showing label ?? id. */
function VariableOptions({ variables, t: _t }: { variables: FuzzyDocument["inputs"]; t: Translate }) {
  return (
    <>
      {variables.map((variable) => (
        <option key={variable.id} value={variable.id}>
          {variable.label ?? variable.id}
        </option>
      ))}
    </>
  );
}

/** Props of one condition row: the clause, its index inside the rule and the update callback. */
interface ConditionRowProps {
  clause: FuzzyClause;
  index: number;
  isRemovable: boolean;
  document: FuzzyDocument;
  onChangeClause: (index: number, next: FuzzyClause) => void;
  onRemove: (index: number) => void;
  t: Translate;
}

/** One `<variable> is <term>` pair, its term select and its remove button. */
function ConditionRow({
  clause,
  index,
  isRemovable,
  document,
  onChangeClause,
  onRemove,
  t,
}: ConditionRowProps) {
  const variable = document.inputs.find((candidate) => candidate.id === clause.variable);
  const terms = variable?.terms ?? [];
  const changeVariable = (nextId: string) => onChangeClause(index, { variable: nextId, is: firstTermName(document, nextId) });
  return (
    <>
      <select aria-label={t("fuzzy.rule.variable")} value={clause.variable} onChange={(event) => changeVariable(event.target.value)}>
        <VariableOptions variables={document.inputs} t={t} />
      </select>
      <span className="rule-word">{t("fuzzy.rule.is")}</span>
      <select aria-label={t("fuzzy.rule.term")} value={clause.is} onChange={(event) => onChangeClause(index, { ...clause, is: event.target.value })}>
        {terms.map((term) => (
          <option key={term.name} value={term.name}>
            {term.name}
          </option>
        ))}
      </select>
      {isRemovable && (
        <button type="button" className="link-button" onClick={() => onRemove(index)}>
          {t("fuzzy.rule.removeCondition")}
        </button>
      )}
    </>
  );
}

/** Props of the operator select shown between two conditions. */
interface OperatorSelectProps {
  operator: "and" | "or";
  onChange: (operator: "and" | "or") => void;
  t: Translate;
}

/** The and/or select; one operator applies to the whole rule. */
function OperatorSelect({ operator, onChange, t }: OperatorSelectProps) {
  return (
    <select aria-label={t("fuzzy.rule.operator")} value={operator} onChange={(event) => onChange(event.target.value as "and" | "or")}>
      <option value="and">{t("fuzzy.rule.and")}</option>
      <option value="or">{t("fuzzy.rule.or")}</option>
    </select>
  );
}

/** Conclusion selects of a rule: output variable and its term. */
function ConclusionSelects({
  clause,
  document,
  onChangeClause,
  t,
}: {
  clause: FuzzyClause;
  document: FuzzyDocument;
  onChangeClause: (next: FuzzyClause) => void;
  t: Translate;
}) {
  const output = document.outputs.find((candidate) => candidate.id === clause.variable);
  const changeVariable = (nextId: string) => onChangeClause({ variable: nextId, is: firstTermName(document, nextId) });
  return (
    <>
      <select aria-label={t("fuzzy.rule.output")} value={clause.variable} onChange={(event) => changeVariable(event.target.value)}>
        <VariableOptions variables={document.outputs} t={t} />
      </select>
      <span className="rule-word">{t("fuzzy.rule.is")}</span>
      <select aria-label={t("fuzzy.rule.term")} value={clause.is} onChange={(event) => onChangeClause({ ...clause, is: event.target.value })}>
        {(output?.terms ?? []).map((term) => (
          <option key={term.name} value={term.name}>
            {term.name}
          </option>
        ))}
      </select>
    </>
  );
}

/** Props of one rule line: the rule, its index and the callbacks that edit it. */
interface RuleRowProps {
  rule: FuzzyRule;
  document: FuzzyDocument;
  firing: number | undefined;
  onChangeRule: (next: FuzzyRule) => void;
  onDelete: () => void;
  t: Translate;
}

/** One rule rendered as a sentence, with weight, enabled flag and firing gauge. */
function RuleRow({ rule, document, firing, onChangeRule, onDelete, t }: RuleRowProps) {
  const operator = rule.operator ?? "and";
  const changeClause = (index: number, next: FuzzyClause) =>
    onChangeRule({ ...rule, if: rule.if.map((clause, position) => (position === index ? next : clause)) });
  const removeClause = (index: number) => onChangeRule({ ...rule, if: rule.if.filter((_, position) => position !== index) });
  const addClause = () => onChangeRule({ ...rule, if: [...rule.if, defaultCondition(document)] });
  return (
    <li className={(rule.enabled ?? true) ? "rule-row" : "rule-row rule-disabled"}>
      <span className="rule-word">{t("fuzzy.rule.if")}</span>
      {rule.if.map((clause, index) => (
        <span className="rule-condition" key={index}>
          <ConditionRow
            clause={clause}
            index={index}
            isRemovable={rule.if.length > 1}
            document={document}
            onChangeClause={changeClause}
            onRemove={removeClause}
            t={t}
          />
          {index < rule.if.length - 1 && (
            <OperatorSelect operator={operator} onChange={(next) => onChangeRule({ ...rule, operator: next })} t={t} />
          )}
        </span>
      ))}
      <button type="button" className="link-button" onClick={addClause}>
        {t("fuzzy.rule.addCondition")}
      </button>
      <span className="rule-word">{t("fuzzy.rule.then")}</span>
      <ConclusionSelects
        clause={rule.then}
        document={document}
        onChangeClause={(next) => onChangeRule({ ...rule, then: next })}
        t={t}
      />
      <RuleSettings rule={rule} firing={firing} onChangeRule={onChangeRule} t={t} />
      <button type="button" className="link-button" onClick={onDelete}>
        {t("fuzzy.rule.delete")}
      </button>
    </li>
  );
}

/** Weight field, enabled checkbox and firing gauge of one rule. */
function RuleSettings({
  rule,
  firing,
  onChangeRule,
  t,
}: {
  rule: FuzzyRule;
  firing: number | undefined;
  onChangeRule: (next: FuzzyRule) => void;
  t: Translate;
}) {
  const toggleEnabled = (enabled: boolean) => onChangeRule({ ...rule, enabled });
  return (
    <>
      <label>
        {t("fuzzy.rule.weight")}
        <input
          type="number"
          min={0}
          max={1}
          step={0.1}
          value={rule.weight ?? 1}
          onChange={(event) => onChangeRule({ ...rule, weight: clampWeight(event.target.value, rule.weight ?? 1) })}
        />
      </label>
      <label>
        <input type="checkbox" checked={rule.enabled ?? true} onChange={(event) => toggleEnabled(event.target.checked)} />
        {t("fuzzy.rule.enabled")}
      </label>
      {firing !== undefined && (
        <span className="rule-firing">
          <progress max={1} value={firing} aria-label={rule.id} />
          {Math.round(firing * 100)}%
        </span>
      )}
    </>
  );
}

/** Props of the button that appends a fresh rule. */
function AddRuleButton({ onAdd, t }: { onAdd: () => void; t: Translate }) {
  return (
    <button type="button" className="filter-chip" onClick={onAdd}>
      {t("fuzzy.rule.add")}
    </button>
  );
}

/** Editor of the whole rule list; edits are immutable and reported through `onChange`. */
export function RulesEditor({
  document,
  onChange,
  firing,
  t,
}: {
  document: FuzzyDocument;
  onChange: (next: FuzzyDocument) => void;
  firing?: Record<string, number>;
  t: Translate;
}) {
  const replaceRule = (index: number, next: FuzzyRule) =>
    onChange({ ...document, rules: document.rules.map((rule, position) => (position === index ? next : rule)) });
  const deleteRule = (index: number) => onChange({ ...document, rules: document.rules.filter((_, position) => position !== index) });
  const addRule = () =>
    onChange({
      ...document,
      rules: [...document.rules, { id: newRuleId(document.rules), if: [defaultCondition(document)], then: defaultConclusion(document) }],
    });
  return (
    <>
      <h3>{t("fuzzy.rules")}</h3>
      <ol className="rules-list">
        {document.rules.map((rule, index) => (
          <RuleRow
            key={rule.id}
            rule={rule}
            document={document}
            firing={firing?.[rule.id]}
            onChangeRule={(next) => replaceRule(index, next)}
            onDelete={() => deleteRule(index)}
            t={t}
          />
        ))}
      </ol>
      <AddRuleButton onAdd={addRule} t={t} />
    </>
  );
}

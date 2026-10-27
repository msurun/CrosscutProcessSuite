// src/components/KnowledgeFields.tsx
//
// Presentational pieces of the knowledge editor: labelled inputs with a collapsible
// "how to measure" text, the measurement-range group and the after-save change list.

import type { ReactNode } from "react";
import type { LoopKnowledgeValues, RangeDefault } from "../api";
import type { Translate } from "../findings";
import type { FieldChange, KnowledgeDraft, RangeFieldName } from "./knowledgeDraft";
import { isDraftFieldValid } from "./knowledgeDraft";

/** Props of one numeric field: label, help, optional how-to text and the current text. */
interface NumberFieldProps {
  id: string;
  label: string;
  help?: string;
  howTo?: ReactNode;
  text: string;
  placeholder: string;
  isValid: boolean;
  invalidMessage: string;
  onChange: (text: string) => void;
}

/** Collapsible "how to measure" text; renders nothing without a body. */
export function HowTo({ summary, body }: { summary: string; body: string }) {
  return (
    <details className="field-howto">
      <summary>{summary}</summary>
      <p>{body}</p>
    </details>
  );
}

/** A labelled decimal input with a help line, optional how-to and a per-field error. */
export function NumberInput({ id, label, help, howTo, text, placeholder, isValid, invalidMessage, onChange }: NumberFieldProps) {
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>{label}</label>
      <input
        id={id}
        className="field-input"
        inputMode="decimal"
        type="text"
        value={text}
        placeholder={placeholder}
        aria-describedby={help ? `${id}-help` : undefined}
        aria-invalid={!isValid}
        onChange={(event) => onChange(event.target.value)}
      />
      {help && <small className="field-help" id={`${id}-help`}>{help}</small>}
      {howTo}
      {!isValid && <p className="status status-error" role="alert">{invalidMessage}</p>}
    </div>
  );
}

/** The process kind selector; the backend only knows self-regulating and integrating. */
export function ProcessKindField({
  value,
  t,
  onChange,
}: {
  value: LoopKnowledgeValues["process_kind"];
  t: Translate;
  onChange: (kind: LoopKnowledgeValues["process_kind"]) => void;
}) {
  return (
    <div className="field">
      <label className="field-label" htmlFor="knowledge-process-kind">
        {t("knowledge.processKind")}
      </label>
      <select
        id="knowledge-process-kind"
        className="field-input"
        value={value}
        aria-describedby="knowledge-process-kind-help"
        onChange={(event) => onChange(event.target.value as LoopKnowledgeValues["process_kind"])}
      >
        <option value="self_regulating">{t("knowledge.kind.self_regulating")}</option>
        <option value="integrating">{t("knowledge.kind.integrating")}</option>
      </select>
      <small className="field-help" id="knowledge-process-kind-help">{t("knowledge.kindHelp")}</small>
      <HowTo summary={t("knowledge.kindExampleTitle")} body={t("knowledge.kindExample")} />
    </div>
  );
}

/** The PID vendor selector: the Tuning tab then shows that block's parameter names. */
export function VendorField({
  value,
  t,
  onChange,
}: {
  value: KnowledgeDraft["vendor"];
  t: Translate;
  onChange: (vendor: KnowledgeDraft["vendor"]) => void;
}) {
  return (
    <div className="field">
      <label className="field-label" htmlFor="knowledge-vendor">
        {t("knowledge.vendor")}
      </label>
      <select
        id="knowledge-vendor"
        className="field-input"
        value={value}
        aria-describedby="knowledge-vendor-help"
        onChange={(event) => onChange(event.target.value as KnowledgeDraft["vendor"])}
      >
        <option value="">{t("knowledge.vendor.none")}</option>
        <option value="siemens_pid_compact">{t("knowledge.vendor.siemens_pid_compact")}</option>
        <option value="abb_pidcc">{t("knowledge.vendor.abb_pidcc")}</option>
      </select>
      <small className="field-help" id="knowledge-vendor-help">{t("knowledge.vendorHelp")}</small>
    </div>
  );
}

/** Placeholder of a range field: the tag-row default when there is one. */
function rangePlaceholder(value: number | null, t: Translate): string {
  return value === null ? t("knowledge.leaveBlank") : t("knowledge.tagDefault", { value });
}

/** One range field (min or max) with the shared validation message. */
function RangeInput(props: {
  name: RangeFieldName;
  label: string;
  draft: KnowledgeDraft;
  fallback: number | null;
  t: Translate;
  onChange: (name: RangeFieldName, text: string) => void;
}) {
  const { name, label, draft, fallback, t, onChange } = props;
  const valid = isDraftFieldValid(draft, name);
  return (
    <div className="field">
      <label className="field-label" htmlFor={`knowledge-${name}`}>{label}</label>
      <input
        id={`knowledge-${name}`}
        className="field-input"
        inputMode="decimal"
        type="text"
        value={draft[name]}
        placeholder={rangePlaceholder(fallback, t)}
        aria-invalid={!valid}
        onChange={(event) => onChange(name, event.target.value)}
      />
      {!valid && <p className="status status-error" role="alert">{t("knowledge.invalidRange")}</p>}
    </div>
  );
}

/** The "Measurement ranges" group: PV and output min/max with precedence hint and how-to. */
export function RangeGroup({
  draft,
  pvDefault,
  outDefault,
  inverted,
  t,
  onChange,
}: {
  draft: KnowledgeDraft;
  pvDefault: RangeDefault;
  outDefault: RangeDefault;
  inverted: Array<"pv" | "out">;
  t: Translate;
  onChange: (name: RangeFieldName, text: string) => void;
}) {
  const row = (name: RangeFieldName, label: string, fallback: number | null) => (
    <RangeInput name={name} label={t(label)} draft={draft} fallback={fallback} t={t} onChange={onChange} />
  );
  return (
    <fieldset className="knowledge-ranges">
      <legend>{t("knowledge.ranges")}</legend>
      <p className="field-help">{t("knowledge.rangesPrecedence")}</p>
      <div className="knowledge-fields">
        {row("pv_eng_min", "knowledge.pvMin", pvDefault.min)}
        {row("pv_eng_max", "knowledge.pvMax", pvDefault.max)}
        {row("out_eng_min", "knowledge.outMin", outDefault.min)}
        {row("out_eng_max", "knowledge.outMax", outDefault.max)}
      </div>
      {inverted.map((which) => (
        <p key={which} className="status status-error" role="alert">
          {t("knowledge.rangeInverted", { range: t(`knowledge.range.${which}`) })}
        </p>
      ))}
      <HowTo summary={t("knowledge.howTo")} body={t("knowledge.howToRanges")} />
    </fieldset>
  );
}

/** Label key of a changed field. */
function changeLabel(name: FieldChange["name"], unit: string, t: Translate): string {
  const keys: Record<FieldChange["name"], string> = {
    delay_s: "knowledge.delay",
    ultimate_period_s: "knowledge.ultimate",
    amplitude_limit: "knowledge.amplitude",
    process_kind: "knowledge.processKind",
    vendor: "knowledge.vendor",
    pv_eng_min: "knowledge.pvMin",
    pv_eng_max: "knowledge.pvMax",
    out_eng_min: "knowledge.outMin",
    out_eng_max: "knowledge.outMax",
  };
  return t(keys[name], { unit });
}

/** A value in the change list: "not set" before, "cleared" after, kind names translated. */
function changeValue(name: FieldChange["name"], value: FieldChange["after"], isAfter: boolean, t: Translate): string {
  if (value === null) return t(isAfter ? "knowledge.cleared" : "knowledge.notSet");
  if (typeof value === "string") return t(name === "vendor" ? `knowledge.vendor.${value}` : `knowledge.kind.${value}`);
  return String(value);
}

/** Dismissible polite list of what a save changed: "label: old -> new". */
export function SaveDiff({
  changes,
  unit,
  t,
  onDismiss,
}: {
  changes: FieldChange[];
  unit: string;
  t: Translate;
  onDismiss: () => void;
}) {
  return (
    <div className="knowledge-diff">
      <p>{t("knowledge.saved")}</p>
      {changes.length > 0 && (
        <ul>
          {changes.map((c) => (
            <li key={c.name}>
              {changeLabel(c.name, unit, t)}: {changeValue(c.name, c.before, false, t)} {"->"} {changeValue(c.name, c.after, true, t)}
            </li>
          ))}
        </ul>
      )}
      <button type="button" className="filter-chip" onClick={onDismiss}>{t("knowledge.dismiss")}</button>
    </div>
  );
}

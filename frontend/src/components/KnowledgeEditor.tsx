// src/components/KnowledgeEditor.tsx
//
// Editor for the per-loop knowledge (dead time, ultimate period, amplitude limit, process
// kind). These values unlock conclusions the backend otherwise withholds, so the form sits
// inside a collapsible panel that starts open when something was not assessed.

import { useEffect, useState } from "react";
import type { LoopKnowledge, LoopKnowledgeUpdate, LoopKnowledgeValues, LoopSummary } from "../api";
import { fetchKnowledge, saveKnowledge } from "../api";
import type { Translate } from "../findings";
import { isPartiallyAssessed } from "../worklist";

/** Result of parsing one numeric field: the value, "not given" for blank, or "invalid". */
export type NumberField = number | null | "invalid";

/** The four fields the user edits, all as text so a decimal comma can be typed. */
interface KnowledgeDraft {
  delay_s: string;
  ultimate_period_s: string;
  amplitude_limit: string;
  process_kind: LoopKnowledgeValues["process_kind"];
}

/** Placeholder shown for every numeric field: blank means "not given". */
const DECIMAL_INPUT_MODE = "decimal";

/** Names of the numeric fields; the process kind is edited separately. */
const NUMERIC_FIELDS = ["delay_s", "ultimate_period_s", "amplitude_limit"] as const;

type NumericFieldName = (typeof NUMERIC_FIELDS)[number];

/** Load state of the loop knowledge: loading, failed, or the values the backend returned. */
type KnowledgeState =
  | { status: "loading" }
  | { status: "error"; reason: string }
  | { status: "ready"; knowledge: LoopKnowledge };

/**
 * Parse one numeric field text.
 *
 * A blank text means "not given" (null); a decimal comma is accepted ("1,5" is 1.5).
 * Returns "invalid" when the text is not a finite number greater than zero.
 */
export function parseNumberField(text: string): NumberField {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  const value = Number(trimmed.replace(",", "."));
  return Number.isFinite(value) && value > 0 ? value : "invalid";
}

/** True when the text is blank or parses to a positive number. */
function isFieldValid(text: string): boolean {
  return parseNumberField(text) !== "invalid";
}

/**
 * Build the update payload with only the fields that differ from the loaded values.
 *
 * A numeric field cleared by the user becomes null so the backend forgets the value.
 * An invalid field is left out; the form already blocks Save in that case.
 */
export function buildUpdate(loaded: LoopKnowledgeValues, draft: KnowledgeDraft): LoopKnowledgeUpdate {
  const update: LoopKnowledgeUpdate = {};
  for (const name of NUMERIC_FIELDS) {
    const parsed = parseNumberField(draft[name]);
    if (parsed === "invalid") continue;
    if (parsed !== loaded[name]) update[name] = parsed;
  }
  if (draft.process_kind !== loaded.process_kind) update.process_kind = draft.process_kind;
  return update;
}

/** The text shown in the numeric inputs for the loaded values; null becomes a blank input. */
function draftFromValues(values: LoopKnowledgeValues): KnowledgeDraft {
  const text = (value: number | null): string => (value === null ? "" : String(value));
  return {
    delay_s: text(values.delay_s),
    ultimate_period_s: text(values.ultimate_period_s),
    amplitude_limit: text(values.amplitude_limit),
    process_kind: values.process_kind,
  };
}

/** True when the draft holds at least one value that differs from the loaded values. */
function hasChanges(loaded: LoopKnowledgeValues, draft: KnowledgeDraft): boolean {
  return Object.keys(buildUpdate(loaded, draft)).length > 0;
}

/**
 * Load the loop knowledge from the backend.
 *
 * Returns the load state; a late response for an older loop is ignored through `cancelled`.
 */
function useKnowledge(datasetId: string, loopName: string): KnowledgeState {
  const [state, setState] = useState<KnowledgeState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });

    fetchKnowledge(datasetId, loopName)
      .then((knowledge) => {
        if (!cancelled) setState({ status: "ready", knowledge });
      })
      .catch((error: unknown) => {
        if (!cancelled) setState({ status: "error", reason: String(error) });
      });

    return () => {
      cancelled = true;
    };
  }, [datasetId, loopName]);

  return state;
}

/** "0 – 100" for a configured range, or undefined when the tag has none. */
function formatRange(range: [number, number] | null): string | undefined {
  return range === null ? undefined : `${range[0]} – ${range[1]}`;
}

/** One read-only range line: the range when configured, a warning notice otherwise. */
function RangeInfo({
  range,
  presentKey,
  missingKey,
  t,
}: {
  range: [number, number] | null;
  presentKey: string;
  missingKey: string;
  t: Translate;
}) {
  const text = formatRange(range);
  if (text === undefined) {
    return <p className="notice notice-warning">{t(missingKey)}</p>;
  }
  return <p>{t(presentKey, { range: text })}</p>;
}

/** Props of one numeric field: its label key, help key and the current text. */
interface NumberFieldProps {
  id: string;
  label: string;
  help: string;
  text: string;
  placeholder: string;
  invalidMessage: string;
  onChange: (text: string) => void;
}

/** A labelled decimal input with a help paragraph and a per-field error. */
function NumberField({
  id,
  label,
  help,
  text,
  placeholder,
  invalidMessage,
  onChange,
}: NumberFieldProps) {
  const isValid = isFieldValid(text);
  const helpId = `${id}-help`;
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className="field-input"
        inputMode={DECIMAL_INPUT_MODE}
        type="text"
        value={text}
        placeholder={placeholder}
        aria-describedby={helpId}
        aria-invalid={!isValid}
        onChange={(event) => onChange(event.target.value)}
      />
      <small className="field-help" id={helpId}>
        {help}
      </small>
      {!isValid && (
        <p className="status status-error" role="alert">
          {invalidMessage}
        </p>
      )}
    </div>
  );
}

/** The process kind selector; the backend only knows self-regulating and integrating. */
function ProcessKindField({
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
        onChange={(event) => onChange(event.target.value as LoopKnowledgeValues["process_kind"])}
      >
        <option value="self_regulating">{t("knowledge.kind.self_regulating")}</option>
        <option value="integrating">{t("knowledge.kind.integrating")}</option>
      </select>
    </div>
  );
}

/** The form plus Save/Undo buttons, shown once the knowledge is loaded. */
function KnowledgeForm({
  datasetId,
  loop,
  knowledge,
  t,
  onSaved,
}: {
  datasetId: string;
  loop: LoopSummary;
  knowledge: LoopKnowledge;
  t: Translate;
  onSaved: () => void;
}) {
  const [loaded, setLoaded] = useState<LoopKnowledge>(knowledge);
  const [draft, setDraft] = useState<KnowledgeDraft>(draftFromValues(knowledge.knowledge));
  const [isSaving, setIsSaving] = useState(false);
  const [savedAt, setSavedAt] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    setLoaded(knowledge);
    setDraft(draftFromValues(knowledge.knowledge));
  }, [knowledge]);

  const isComplete = NUMERIC_FIELDS.every((name) => isFieldValid(draft[name]));
  const isChanged = hasChanges(loaded.knowledge, draft);
  const canSave = isComplete && isChanged && !isSaving;
  const placeholder = t("knowledge.leaveBlank");

  /** Set one numeric field, clearing the previous status messages. */
  const setNumeric = (name: NumericFieldName, text: string): void => {
    setDraft((current) => ({ ...current, [name]: text }));
    setSavedAt(false);
    setSaveError(null);
  };

  /** Restore the loaded values; the backend keeps its copy untouched. */
  const reset = (): void => {
    setDraft(draftFromValues(loaded.knowledge));
    setSavedAt(false);
    setSaveError(null);
  };

  /** Send only the changed fields and adopt the response as the new baseline. */
  const submit = async (event: React.FormEvent): Promise<void> => {
    event.preventDefault();
    setIsSaving(true);
    setSavedAt(false);
    setSaveError(null);
    try {
      const update = buildUpdate(loaded.knowledge, draft);
      const saved = await saveKnowledge(datasetId, loop.name, update);
      setLoaded(saved);
      setDraft(draftFromValues(saved.knowledge));
      setSavedAt(true);
      onSaved();
    } catch (error: unknown) {
      setSaveError(String(error));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <form onSubmit={submit}>
      <div className="knowledge-fields">
        <NumberField
          id="knowledge-delay"
          label={t("knowledge.delay")}
          help={t("knowledge.delayHelp")}
          text={draft.delay_s}
          placeholder={placeholder}
          invalidMessage={t("knowledge.invalid")}
          onChange={(text) => setNumeric("delay_s", text)}
        />
        <NumberField
          id="knowledge-ultimate"
          label={t("knowledge.ultimate")}
          help={t("knowledge.ultimateHelp")}
          text={draft.ultimate_period_s}
          placeholder={placeholder}
          invalidMessage={t("knowledge.invalid")}
          onChange={(text) => setNumeric("ultimate_period_s", text)}
        />
        <NumberField
          id="knowledge-amplitude"
          label={t("knowledge.amplitude", { unit: loop.unit })}
          help={t("knowledge.amplitudeHelp")}
          text={draft.amplitude_limit}
          placeholder={placeholder}
          invalidMessage={t("knowledge.invalid")}
          onChange={(text) => setNumeric("amplitude_limit", text)}
        />
        <ProcessKindField
          value={draft.process_kind}
          t={t}
          onChange={(kind) => setDraft((current) => ({ ...current, process_kind: kind }))}
        />
      </div>

      <RangeInfo
        range={loaded.ranges.out}
        presentKey="knowledge.rangeOut"
        missingKey="knowledge.rangeOutMissing"
        t={t}
      />
      <RangeInfo
        range={loaded.ranges.pv}
        presentKey="knowledge.rangePv"
        missingKey="knowledge.rangePvMissing"
        t={t}
      />

      <p className="form-actions">
        <button type="submit" className="filter-chip" disabled={!canSave}>
          {isSaving ? t("knowledge.saving") : t("knowledge.save")}
        </button>{" "}
        <button type="button" className="filter-chip" onClick={reset}>
          {t("knowledge.reset")}
        </button>
      </p>

      {savedAt && <p role="status">{t("knowledge.saved")}</p>}
      {saveError !== null && (
        <p className="status status-error" role="alert">
          {t("knowledge.error", { reason: saveError })}
        </p>
      )}
    </form>
  );
}

/**
 * Collapsible editor for the per-loop knowledge.
 *
 * Loads the current values, lets the user fill or clear them and saves the changes to the
 * dataset's project.json. On success it calls `onSaved` so the caller can refetch the loops.
 */
export function KnowledgeEditor({
  datasetId,
  loop,
  t,
  onSaved,
}: {
  datasetId: string;
  loop: LoopSummary;
  t: Translate;
  onSaved: () => void;
}) {
  const state = useKnowledge(datasetId, loop.name);

  return (
    <details className="knowledge-editor" open={isPartiallyAssessed(loop)}>
      <summary>{t("knowledge.title")}</summary>
      <p>{t("knowledge.intro")}</p>
      {state.status === "loading" && <p className="status">{t("knowledge.loading")}</p>}
      {state.status === "error" && (
        <p className="status status-error">{t("knowledge.error", { reason: state.reason })}</p>
      )}
      {state.status === "ready" && (
        <KnowledgeForm
          datasetId={datasetId}
          loop={loop}
          knowledge={state.knowledge}
          t={t}
          onSaved={onSaved}
        />
      )}
    </details>
  );
}

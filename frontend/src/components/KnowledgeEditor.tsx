// src/components/KnowledgeEditor.tsx
//
// Editor for the per-loop knowledge (dead time, ultimate period, amplitude limit, process
// kind, measurement ranges). These values unlock conclusions the backend otherwise withholds,
// so the form sits in a collapsible panel that starts open when something was not assessed.

import { useEffect, useState } from "react";
import type { LoopKnowledge, LoopSummary } from "../api";
import { fetchKnowledge, saveKnowledge } from "../api";
import type { Translate } from "../findings";
import { isPartiallyAssessed } from "../worklist";
import type { KnowledgeProposalResponse } from "../knowledgeProposalApi";
import { HowTo, NumberInput, ProcessKindField, RangeGroup, SaveDiff, VendorField } from "./KnowledgeFields";
import type { DraftFieldName, FieldChange, KnowledgeDraft } from "./knowledgeDraft";
import {
  buildUpdate,
  diffValues,
  draftFromValues,
  hasChanges,
  invertedRanges,
  isDraftFieldValid,
  isDraftValid,
  parseNumberField,
} from "./knowledgeDraft";
import { acceptAllHighPatch, FieldProposal, OtherProposals, ProposalBar, useProposal } from "./KnowledgeProposals";
import { DraftNotice } from "./DraftNotice";

export { buildUpdate, parseNumberField };
export type { NumberField } from "./knowledgeDraft";

/** Load state of the loop knowledge: loading, failed, or the values the backend returned. */
type KnowledgeState =
  | { status: "loading" }
  | { status: "error"; reason: string }
  | { status: "ready"; knowledge: LoopKnowledge };

/** Load the loop knowledge; a late response for an older loop is ignored through `cancelled`. */
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
function RangeInfo({ range, presentKey, missingKey, t }: {
  range: [number, number] | null;
  presentKey: string;
  missingKey: string;
  t: Translate;
}) {
  const text = formatRange(range);
  if (text === undefined) return <p className="notice notice-warning">{t(missingKey)}</p>;
  return <p>{t(presentKey, { range: text })}</p>;
}

/** Diff of the last save and the save error, with a reset of both. */
function useSaveStatus() {
  const [changes, setChanges] = useState<FieldChange[] | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const clearStatus = (): void => {
    setChanges(null);
    setSaveError(null);
  };
  return { changes, setChanges, saveError, setSaveError, clearStatus };
}

/** State and actions of the form: draft, save status, the diff of the last save. */
function useKnowledgeForm(datasetId: string, loopName: string, knowledge: LoopKnowledge, onSaved: () => void) {
  const [loaded, setLoaded] = useState<LoopKnowledge>(knowledge);
  const [draft, setDraft] = useState<KnowledgeDraft>(draftFromValues(knowledge.knowledge));
  const [isSaving, setIsSaving] = useState(false);
  const { changes, setChanges, saveError, setSaveError, clearStatus } = useSaveStatus();

  useEffect(() => {
    setLoaded(knowledge);
    setDraft(draftFromValues(knowledge.knowledge));
  }, [knowledge]);

  const edit = (patch: Partial<KnowledgeDraft>): void => {
    setDraft((current) => ({ ...current, ...patch }));
    clearStatus();
  };
  const reset = (): void => {
    setDraft(draftFromValues(loaded.knowledge));
    clearStatus();
  };
  const submit = async (event: React.FormEvent): Promise<void> => {
    event.preventDefault();
    setIsSaving(true);
    clearStatus();
    try {
      const update = buildUpdate(loaded.knowledge, draft);
      const saved = await saveKnowledge(datasetId, loopName, update);
      setChanges(diffValues(loaded.knowledge, saved.knowledge));
      setLoaded(saved);
      setDraft(draftFromValues(saved.knowledge));
      onSaved();
    } catch (error: unknown) {
      setSaveError(String(error));
    } finally {
      setIsSaving(false);
    }
  };
  return { loaded, draft, isSaving, changes, saveError, edit, reset, submit, dismiss: clearStatus };
}

/** The three positive-number fields and the process kind, each with a how-to text. */
function BasicFields({ draft, unit, t, edit, proposal }: {
  draft: KnowledgeDraft;
  unit: string;
  t: Translate;
  edit: (patch: Partial<KnowledgeDraft>) => void;
  proposal: KnowledgeProposalResponse | null;
}) {
  const hint = (name: string) => <FieldProposal name={name} response={proposal} t={t} onAccept={edit} />;
  const field = (name: DraftFieldName, id: string, label: string, [help, how]: [string, string]) => (
    <NumberInput
      id={id}
      label={label}
      help={t(help)}
      howTo={<><HowTo summary={t("knowledge.howTo")} body={t(how)} />{hint(name)}</>}
      text={draft[name]}
      placeholder={t("knowledge.leaveBlank")}
      isValid={isDraftFieldValid(draft, name)}
      invalidMessage={t("knowledge.invalid")}
      onChange={(text) => edit({ [name]: text })}
    />
  );
  return (
    <div className="knowledge-fields">
      {field("delay_s", "knowledge-delay", t("knowledge.delay"), ["knowledge.delayHelp", "knowledge.howToDelay"])}
      {field("ultimate_period_s", "knowledge-ultimate", t("knowledge.ultimate"), ["knowledge.ultimateHelp", "knowledge.howToUltimate"])}
      {field("amplitude_limit", "knowledge-amplitude", t("knowledge.amplitude", { unit }), ["knowledge.amplitudeHelp", "knowledge.howToAmplitude"])}
      <ProcessKindField value={draft.process_kind} t={t} onChange={(kind) => edit({ process_kind: kind })} />
      {hint("process_kind")}
      <VendorField value={draft.vendor} t={t} onChange={(vendor) => edit({ vendor })} />
    </div>
  );
}

/** Save status below the buttons: the change list (live region) or the error alert. */
function SaveStatus({ changes, error, unit, t, onDismiss }: {
  changes: FieldChange[] | null;
  error: string | null;
  unit: string;
  t: Translate;
  onDismiss: () => void;
}) {
  return (
    <>
      <div aria-live="polite">
        {changes !== null && <SaveDiff changes={changes} unit={unit} t={t} onDismiss={onDismiss} />}
      </div>
      {error !== null && (
        <p className="status status-error" role="alert">{t("knowledge.error", { reason: error })}</p>
      )}
    </>
  );
}

/** The Save and Undo buttons. */
function FormActions({ canSave, isSaving, onReset, t }: {
  canSave: boolean;
  isSaving: boolean;
  onReset: () => void;
  t: Translate;
}) {
  return (
    <p className="form-actions">
      <button type="submit" className="filter-chip" disabled={!canSave}>
        {isSaving ? t("knowledge.saving") : t("knowledge.save")}
      </button>{" "}
      <button type="button" className="filter-chip" onClick={onReset}>{t("knowledge.reset")}</button>
    </p>
  );
}

/** The form plus Save/Undo buttons, shown once the knowledge is loaded. */
function KnowledgeForm({ datasetId, loop, knowledge, t, onSaved, onOpenSteps }: {
  datasetId: string;
  loop: LoopSummary;
  knowledge: LoopKnowledge;
  t: Translate;
  onSaved: () => void;
  onOpenSteps?: () => void;
}) {
  const form = useKnowledgeForm(datasetId, loop.name, knowledge, onSaved);
  const { state, load } = useProposal(datasetId, loop.name);
  const response = state.status === "ready" ? state.response : null;
  const { loaded, draft } = form;
  const inverted = invertedRanges(draft);
  const canSave =
    isDraftValid(draft) && inverted.length === 0 && hasChanges(loaded.knowledge, draft) && !form.isSaving;

  return (
    <form onSubmit={form.submit}>
      <ProposalBar
        state={state}
        t={t}
        onLoad={load} onOpenSteps={onOpenSteps}
        onAcceptHigh={() => response && form.edit(acceptAllHighPatch(response.proposals))}
      />
      <BasicFields draft={draft} unit={loop.unit} t={t} edit={form.edit} proposal={response} />
      <RangeGroup
        draft={draft}
        pvDefault={loaded.pv_eng_default}
        outDefault={loaded.out_eng_default}
        inverted={inverted}
        t={t}
        onChange={(name, text) => form.edit({ [name]: text })}
      />
      <OtherProposals response={response} t={t} onAccept={form.edit} />
      <RangeInfo range={loaded.ranges.out} presentKey="knowledge.rangeOut" missingKey="knowledge.rangeOutMissing" t={t} />
      <RangeInfo range={loaded.ranges.pv} presentKey="knowledge.rangePv" missingKey="knowledge.rangePvMissing" t={t} />
      <FormActions canSave={canSave} isSaving={form.isSaving} onReset={form.reset} t={t} />
      <SaveStatus changes={form.changes} error={form.saveError} unit={loop.unit} t={t} onDismiss={form.dismiss} />
      {form.changes !== null && <DraftNotice t={t} />}
    </form>
  );
}

/**
 * Collapsible editor for the per-loop knowledge.
 *
 * Loads the current values, lets the user fill or clear them and saves the changes to the
 * site catalogue (Site) on this computer. On success it calls `onSaved` so the caller can
 * refetch the loops.
 */
export function KnowledgeEditor({ datasetId, loop, t, onSaved, onOpenSteps }: {
  datasetId: string;
  loop: LoopSummary;
  t: Translate;
  onSaved: () => void;
  onOpenSteps?: () => void;
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
        <KnowledgeForm datasetId={datasetId} loop={loop} knowledge={state.knowledge} t={t} onSaved={onSaved} onOpenSteps={onOpenSteps} />
      )}
    </details>
  );
}

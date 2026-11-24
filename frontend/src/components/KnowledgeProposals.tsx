// src/components/KnowledgeProposals.tsx
//
// "Propose from history" pieces of the knowledge editor: the button and notices, and one
// proposal row (value, confidence, evidence, Accept). Accepting only fills the form.

import { useState } from "react";
import type { Translate } from "../findings";
import type { KnowledgeProposal, KnowledgeProposalResponse } from "../knowledgeProposalApi";
import { fetchKnowledgeProposal } from "../knowledgeProposalApi";
import type { KnowledgeDraft } from "./knowledgeDraft";

/** Keys the form can fill; any other proposal key is shown read-only. */
const FORM_KEYS = [
  "delay_s", "ultimate_period_s", "amplitude_limit", "process_kind",
  "pv_eng_min", "pv_eng_max", "out_eng_min", "out_eng_max",
];

/** The amplitude limit is never accepted in bulk: the user must confirm it. */
const CONFIRM_KEY = "amplitude_limit";

/** Keys the form shows inline next to its own field. */
const INLINE_KEYS = ["delay_s", "ultimate_period_s", "amplitude_limit", "process_kind"];

/** True when the form has a field for this proposal key. */
function isFormKey(key: string): boolean {
  return FORM_KEYS.includes(key);
}

/** The draft patch that accepting `proposal` for `key` makes, or null when there is no value. */
export function acceptPatch(key: string, proposal: KnowledgeProposal): Partial<KnowledgeDraft> | null {
  const { value } = proposal;
  if (value === null || !isFormKey(key)) return null;
  if (key === "process_kind") {
    return value === "integrating" || value === "self_regulating" ? { process_kind: value } : null;
  }
  return typeof value === "number" ? { [key]: String(value) } : null;
}

/** The patch of every high-confidence proposal except the one that must be confirmed. */
export function acceptAllHighPatch(proposals: Record<string, KnowledgeProposal>): Partial<KnowledgeDraft> {
  let patch: Partial<KnowledgeDraft> = {};
  for (const [key, proposal] of Object.entries(proposals)) {
    if (proposal.confidence !== "high" || key === CONFIRM_KEY) continue;
    patch = { ...patch, ...acceptPatch(key, proposal) };
  }
  return patch;
}

/** A window as local start - end times; "no window" when the evidence has none. */
function formatWindow(window: [number, number] | null, t: Translate): string {
  if (window === null) return t("knowledgeProposal.noWindow");
  const [start, end] = window.map((s) => new Date(s * 1000).toLocaleString());
  return `${start} - ${end}`;
}

/** Collapsible evidence of one proposal: kind, window, event count and the backend note. */
function Evidence({ proposal, t }: { proposal: KnowledgeProposal; t: Translate }) {
  const { kind, window, events, detail } = proposal.evidence;
  return (
    <details className="field-howto">
      <summary>{t("knowledgeProposal.evidence")}</summary>
      <ul>
        <li>{t("knowledgeProposal.kind", { kind })}</li>
        <li>{t("knowledgeProposal.window", { window: formatWindow(window, t) })}</li>
        <li>{t("knowledgeProposal.events", { events })}</li>
        <li>{detail}</li>
      </ul>
    </details>
  );
}

/** One proposal: the value, a confidence badge, the evidence and (for form keys) Accept. */
function ProposalRow({ name, proposal, t, onAccept }: {
  name: string;
  proposal: KnowledgeProposal;
  t: Translate;
  onAccept?: (patch: Partial<KnowledgeDraft>) => void;
}) {
  const patch = acceptPatch(name, proposal);
  const shown = proposal.value === null ? t("knowledgeProposal.noValue") : String(proposal.value);
  return (
    <div className="knowledge-proposal">
      <span>{t("knowledgeProposal.proposed", { name, value: shown })}</span>{" "}
      <span className={`badge badge-${proposal.confidence}`}>
        {t("knowledgeProposal.confidence", { level: t(`knowledgeProposal.level.${proposal.confidence}`) })}
      </span>
      {name === CONFIRM_KEY && <p className="notice notice-warning">{t("knowledgeProposal.mustConfirm")}</p>}
      {patch !== null && onAccept && (
        <button
          type="button"
          className="filter-chip"
          aria-label={t("knowledgeProposal.acceptField", { name })}
          onClick={() => onAccept(patch)}
        >
          {t("knowledgeProposal.accept")}
        </button>
      )}
      <Evidence proposal={proposal} t={t} />
    </div>
  );
}

/** The proposal of one form field, or nothing when there is none. */
export function FieldProposal({ name, response, t, onAccept }: {
  name: string;
  response: KnowledgeProposalResponse | null;
  t: Translate;
  onAccept: (patch: Partial<KnowledgeDraft>) => void;
}) {
  const proposal = response?.proposals[name];
  if (proposal === undefined) return null;
  return <ProposalRow name={name} proposal={proposal} t={t} onAccept={onAccept} />;
}

/** Proposals without an inline field: the range keys (acceptable) and unknown keys (read-only). */
export function OtherProposals({ response, t, onAccept }: {
  response: KnowledgeProposalResponse | null;
  t: Translate;
  onAccept: (patch: Partial<KnowledgeDraft>) => void;
}) {
  const rest = Object.entries(response?.proposals ?? {}).filter(([key]) => !INLINE_KEYS.includes(key));
  if (rest.length === 0) return null;
  return (
    <div>
      {rest.map(([key, proposal]) => (
        <ProposalRow key={key} name={key} proposal={proposal} t={t} onAccept={isFormKey(key) ? onAccept : undefined} />
      ))}
    </div>
  );
}

/** Load state of a proposal request. */
export type ProposalState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; reason: string }
  | { status: "ready"; response: KnowledgeProposalResponse };

/** Fetch on demand; a failure is kept as state so the editor can show it. */
export function useProposal(datasetId: string, loopName: string) {
  const [state, setState] = useState<ProposalState>({ status: "idle" });
  const load = (): void => {
    setState({ status: "loading" });
    fetchKnowledgeProposal(datasetId, loopName)
      .then((response) => setState({ status: "ready", response }))
      .catch((error: unknown) => setState({ status: "error", reason: String(error) }));
  };
  return { state, load };
}

/** Button, status line, step-test notice and "accept all high-confidence". */
export function ProposalBar({ state, t, onLoad, onAcceptHigh, onOpenSteps }: {
  state: ProposalState;
  t: Translate;
  onLoad: () => void;
  onAcceptHigh: () => void;
  onOpenSteps?: () => void;
}) {
  return (
    <div className="knowledge-proposal-bar">
      <button type="button" className="filter-chip" disabled={state.status === "loading"} onClick={onLoad}>
        {state.status === "loading" ? t("knowledgeProposal.loading") : t("knowledgeProposal.propose")}
      </button>
      {state.status === "ready" && (
        <>
          {" "}
          <button type="button" className="filter-chip" onClick={onAcceptHigh}>{t("knowledgeProposal.acceptHigh")}</button>
        </>
      )}
      {state.status === "error" && (
        <p className="status status-error" role="alert">{t("knowledgeProposal.error", { reason: state.reason })}</p>
      )}
      {state.status === "ready" && state.response.needs_step_test && (
        <p className="notice notice-warning">
          {t("knowledgeProposal.needsStepTest")}{" "}
          {onOpenSteps && (
            <button type="button" className="link-button" onClick={onOpenSteps}>{t("knowledgeProposal.openSteps")}</button>
          )}
        </p>
      )}
    </div>
  );
}

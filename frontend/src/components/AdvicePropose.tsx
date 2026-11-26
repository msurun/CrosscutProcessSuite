// "Propose" action of a logged advice: asks for confirmation, sends the advice to the supervisor's
// propose route and shows the answer as an advisory proposal. The page never writes to a plant: the
// Write Gateway decides, and in confirm mode a person approves the proposal there.
import { useState } from "react";
import type { SupervisorProposeResult } from "../api";
import type { Translate } from "../findings";
import { formatNumber } from "../advisory";
import { describeError } from "./AdvisoryState";

interface ProposeProps {
  onPropose: () => Promise<SupervisorProposeResult>;
  t: Translate;
}

/** The proposal the gateway received and what it answered. */
export function ProposalResult({ result, t }: { result: SupervisorProposeResult; t: Translate }) {
  const { proposal, decision } = result;
  const verdict = decision.accepted === false ? "advisory.propose.refused" : "advisory.propose.accepted";
  return (
    <div className="notice" role="status" data-testid="propose-result">
      <p>
        {t("advisory.propose.summary", { tag: proposal.target_tag, value: formatNumber(proposal.value), reason: proposal.reason })}
      </p>
      <p>
        {t(verdict, { code: decision.reason_code ?? "-" })}{" "}
        {result.queues_for_approval ? t("advisory.propose.queued") : t("advisory.propose.direct", { mode: result.mode })}
      </p>
    </div>
  );
}

/** Propose button, its confirmation step and the result or error. */
export function ProposeAction({ onPropose, t }: ProposeProps) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<SupervisorProposeResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const send = () => {
    setBusy(true);
    setError(null);
    onPropose()
      .then((answer) => { setResult(answer); setAsking(false); })
      .catch((failure: unknown) => setError(describeError(failure)))
      .finally(() => setBusy(false));
  };
  return (
    <div className="advice-propose">
      {result === null && !asking && (
        <button type="button" className="filter-chip" onClick={() => setAsking(true)}>{t("advisory.propose.button")}</button>
      )}
      {asking && result === null && (
        <div className="notice" role="group" aria-label={t("advisory.propose.button")}>
          <p>{t("advisory.propose.confirm")}</p>
          <div className="toolbar">
            <button type="button" className="filter-chip" disabled={busy} onClick={send}>{t("advisory.propose.send")}</button>
            <button type="button" className="filter-chip" disabled={busy} onClick={() => setAsking(false)}>{t("advisory.propose.cancel")}</button>
          </div>
        </div>
      )}
      {error !== null && <p className="status status-error" role="alert">{t("trends.error", { reason: error })}</p>}
      {result !== null && <ProposalResult result={result} t={t} />}
    </div>
  );
}

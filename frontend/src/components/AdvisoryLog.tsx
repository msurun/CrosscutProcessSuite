// Log view of the Advisory page: the chain status ("chain verified" or a "chain broken" alert) and
// the newest logged advices with the recorded decision of each. Decisions are made here and POSTed
// as acknowledgements; after one the log is reloaded so the page shows what is really stored.
import { ackAdvice, type AckDecision, type AdvisoryLog as AdvisoryLogData, type ChainReport } from "../api";
import type { Translate } from "../findings";
import { advicesNewestFirst, latestAcks, type AckDraft } from "../advisory";
import { AdviceCard } from "./AdviceCard";

/** How many logged advices are drawn (newest first). */
const MAX_SHOWN = 20;

/** "Chain verified" as a status, a broken chain as an alert (record numbers start at 1). */
export function ChainStatus({ chain, t }: { chain: ChainReport; t: Translate }) {
  if (chain.ok) {
    return <p className="status" role="status">{t("advisory.log.chainOk", { count: chain.records })}</p>;
  }
  const record = (chain.first_broken_index ?? 0) + 1;
  return (
    <p className="notice notice-warning" role="alert">
      {t("advisory.log.chainBroken", { record, reason: chain.reason })}
    </p>
  );
}

interface AdvisoryLogProps {
  supervisorId: string;
  log: AdvisoryLogData | null;
  error: string | null;
  t: Translate;
  onChanged: () => void;
}

/** The audit log of one supervisor. */
export function AdvisoryLog({ supervisorId, log, error, t, onChanged }: AdvisoryLogProps) {
  const decide = async (adviceId: string, decision: AckDecision, draft: AckDraft) => {
    await ackAdvice(supervisorId, adviceId, { decision, reasonCode: draft.reasonCode, who: draft.who.trim(), note: draft.note });
    onChanged();
  };
  const advices = log === null ? [] : advicesNewestFirst(log.records);
  const acks = log === null ? new Map() : latestAcks(log.records);
  return (
    <section aria-label={t("advisory.log.title")}>
      <h3>{t("advisory.log.title")}</h3>
      <p className="hint">{t("advisory.log.hint")}</p>
      {error !== null && <p className="status status-error" role="alert">{t("trends.error", { reason: error })}</p>}
      {log === null && error === null && <p className="status">{t("trends.loading")}</p>}
      {log !== null && <ChainStatus chain={log.chain} t={t} />}
      {log !== null && advices.length === 0 && <p className="status">{t("advisory.log.empty")}</p>}
      {advices.length > MAX_SHOWN && <p className="hint">{t("advisory.log.capped", { shown: MAX_SHOWN, total: advices.length })}</p>}
      <ul className="advice-list">
        {advices.slice(0, MAX_SHOWN).map((advice) => (
          <AdviceCard
            key={advice.advice_id}
            advice={advice}
            ack={acks.get(advice.advice_id)}
            t={t}
            onDecide={(decision, draft) => decide(advice.advice_id, decision, draft)}
          />
        ))}
      </ul>
    </section>
  );
}

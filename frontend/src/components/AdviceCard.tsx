// One advice as a card: direction (icon and word), magnitude, activation, gate badge with reasons,
// the explanation sentences and, in the log, the recorded decision with Accept / Reject / Defer
// buttons. The wording never suggests that the system acts: a person decides and the log records it.
import { useState } from "react";
import type { Translate } from "../findings";
import {
  DECISIONS,
  DIRECTION_ICON,
  formatAdviceTime,
  formatNumber,
  gateChipClass,
  type AckDraft,
} from "../advisory";
import type { AckDecision, AckRecord, AdviceRecord } from "../api";
import { AckForm } from "./AckForm";

interface AdviceCardProps {
  advice: AdviceRecord;
  t: Translate;
  /** The newest recorded decision of this advice, when there is one. */
  ack?: AckRecord;
  /** When given, the card offers the three "Record decision" buttons (only for logged advice). */
  onDecide?: (decision: AckDecision, draft: AckDraft) => Promise<void>;
}

/** Direction as icon plus word. */
function Direction({ advice, t }: { advice: AdviceRecord; t: Translate }) {
  return (
    <strong className="advice-direction">
      <span aria-hidden="true">{DIRECTION_ICON[advice.direction]} </span>
      {t(`advisory.direction.${advice.direction}`)}
    </strong>
  );
}

/** Magnitude (unit-less), activation and time of an advice. */
function Figures({ advice, t }: { advice: AdviceRecord; t: Translate }) {
  const hasMagnitude = advice.magnitude !== null && advice.magnitude !== undefined;
  return (
    <p className="advice-figures">
      {hasMagnitude ? t("advisory.magnitude", { value: formatNumber(advice.magnitude) }) : t("advisory.noMagnitude")}
      {" · "}
      {t("advisory.activation", { value: formatNumber(advice.activation) })}
      {" · "}
      <time>{formatAdviceTime(advice.t_ns)}</time>
    </p>
  );
}

/** Gate badge with the reasons behind it. */
function GateBadge({ advice, t }: { advice: AdviceRecord; t: Translate }) {
  const { state, reasons } = advice.gate;
  return (
    <p className="advice-gate">
      <span className={gateChipClass(state)}>{t("advisory.gate", { state: t(`advisory.gate.${state}`) })}</span>
      {reasons.length > 0 && <span> {t("advisory.gate.reasons", { reasons: reasons.join(", ") })}</span>}
    </p>
  );
}

/** The recorded decision of an advice, or a note that none is recorded yet. */
function AckState({ ack, t }: { ack?: AckRecord; t: Translate }) {
  if (ack === undefined) return <p className="hint advice-ack">{t("advisory.ack.none")}</p>;
  return (
    <p className="advice-ack">
      {t("advisory.ack.recorded", {
        decision: t(`advisory.decision.${ack.decision}`),
        who: ack.who,
        reason: t(`advisory.reason.${ack.reason_code}`),
        time: formatAdviceTime(ack.t_ns),
      })}
      {ack.note !== undefined && ack.note !== "" && <em> {ack.note}</em>}
    </p>
  );
}

/** The three decision buttons and, after a click, the form for that decision. */
function Decisions({ onDecide, t }: { onDecide: NonNullable<AdviceCardProps["onDecide"]>; t: Translate }) {
  const [open, setOpen] = useState<AckDecision | null>(null);
  const submit = async (draft: AckDraft) => {
    if (open === null) return;
    await onDecide(open, draft);
    setOpen(null);
  };
  return (
    <>
      <div className="toolbar">
        {DECISIONS.map((decision) => (
          <button key={decision} type="button" className="filter-chip" aria-expanded={open === decision} onClick={() => setOpen(decision)}>
            {t(`advisory.decide.${decision}`)}
          </button>
        ))}
      </div>
      {open !== null && <AckForm key={open} decision={open} t={t} onSubmit={submit} onCancel={() => setOpen(null)} />}
    </>
  );
}

/** The card of one advice. */
export function AdviceCard({ advice, t, ack, onDecide }: AdviceCardProps) {
  return (
    <li className="advice-card">
      <Direction advice={advice} t={t} />
      <Figures advice={advice} t={t} />
      <GateBadge advice={advice} t={t} />
      {advice.explanation.length > 0 && (
        <ul className="advice-explanation">
          {advice.explanation.map((reason) => (
            <li key={reason.rule_id}>{reason.sentence}</li>
          ))}
        </ul>
      )}
      {(ack !== undefined || onDecide !== undefined) && <AckState ack={ack} t={t} />}
      {onDecide !== undefined && <Decisions onDecide={onDecide} t={t} />}
    </li>
  );
}

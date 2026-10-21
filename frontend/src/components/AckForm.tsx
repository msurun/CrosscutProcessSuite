// Small form in which a person records a decision about one logged advice: reason code,
// free-text note and who decided. Both the reason and "who" are required. It only records;
// nothing is sent to a plant.
import { useId, useState } from "react";
import type { Translate } from "../findings";
import { ackIsValid, REASON_CODES, validateAck, type AckDraft } from "../advisory";
import type { AckDecision } from "../api";

interface AckFormProps {
  decision: AckDecision;
  t: Translate;
  /** Called with the valid draft; a rejected promise shows its message under the form. */
  onSubmit: (draft: AckDraft) => Promise<void>;
  onCancel: () => void;
}

const EMPTY_DRAFT: AckDraft = { reasonCode: "", who: "", note: "" };

/** The form for one decision; `decision` only names the form, the buttons carry the choice. */
export function AckForm({ decision, t, onSubmit, onCancel }: AckFormProps) {
  const [draft, setDraft] = useState<AckDraft>(EMPTY_DRAFT);
  const [submitted, setSubmitted] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const idBase = useId();
  const errors = validateAck(draft);
  const change = (field: keyof AckDraft, value: string) => setDraft((previous) => ({ ...previous, [field]: value }));

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (!ackIsValid(errors)) return;
    onSubmit(draft).catch((error: unknown) => setFailure(error instanceof Error ? error.message : String(error)));
  };

  return (
    <form className="ack-form" onSubmit={submit} noValidate aria-label={t(`advisory.decide.${decision}`)}>
      <label className="field" htmlFor={`${idBase}-reason`}>
        <span className="field-label">{t("advisory.ack.reason")}</span>
        <select
          id={`${idBase}-reason`}
          className="field-input"
          value={draft.reasonCode}
          aria-invalid={submitted && errors.reasonCode}
          onChange={(event) => change("reasonCode", event.target.value)}
        >
          <option value="">{t("advisory.ack.reasonPlaceholder")}</option>
          {REASON_CODES.map((code) => (
            <option key={code} value={code}>{t(`advisory.reason.${code}`)}</option>
          ))}
        </select>
      </label>
      <label className="field" htmlFor={`${idBase}-who`}>
        <span className="field-label">{t("advisory.ack.who")}</span>
        <input
          id={`${idBase}-who`}
          className="field-input"
          type="text"
          value={draft.who}
          aria-invalid={submitted && errors.who}
          onChange={(event) => change("who", event.target.value)}
        />
      </label>
      <label className="field" htmlFor={`${idBase}-note`}>
        <span className="field-label">{t("advisory.ack.note")}</span>
        <textarea id={`${idBase}-note`} className="field-input" rows={2} value={draft.note} onChange={(event) => change("note", event.target.value)} />
      </label>
      {submitted && !ackIsValid(errors) && <p className="status status-error" role="alert">{t("advisory.ack.required")}</p>}
      {failure !== null && <p className="status status-error" role="alert">{t("trends.error", { reason: failure })}</p>}
      <p className="hint">{t("advisory.ack.hint")}</p>
      <div className="toolbar">
        <button type="submit" className="filter-chip">{t("advisory.ack.submit")}</button>
        <button type="button" className="filter-chip" onClick={onCancel}>{t("advisory.ack.cancel")}</button>
      </div>
    </form>
  );
}

// Lab results of the Soft sensor page: paste CSV text or choose a CSV file (columns sample_time and
// value), optionally with the ISO time of the first sample, upload it and read back the count and
// the first and last time. Problems are shown with the API's own message (it names the line).
import { useState } from "react";
import { uploadSoftSensorLab, type LabSummary } from "../api";
import type { Translate } from "../findings";
import { formatFixed } from "../format";
import { checkLabText } from "../softsensor";
import { toHours } from "../anomaly";
import { describeSoftError, type StoredState } from "./SoftSensorState";

const HOUR_DECIMALS = 2;
const TEXT_ROWS = 6;

interface LabProps {
  sid: string;
  lab: StoredState<LabSummary>;
  /** ISO time offered as the origin of ISO sample times (the first sample of the dataset). */
  originDefault: string;
  t: Translate;
}

/** What is stored: the count and the first and last time, or the "none" text. */
function LabStored({ summary, t }: { summary: LabSummary | null; t: Translate }) {
  if (summary === null) return <p className="status" data-testid="soft-lab-none">{t("soft.lab.none")}</p>;
  const first = formatFixed(toHours(summary.first_s), HOUR_DECIMALS);
  const last = formatFixed(toHours(summary.last_s), HOUR_DECIMALS);
  return <p className="status" role="status" data-testid="soft-lab-stored">{t("soft.lab.stored", { count: summary.count, first, last })}</p>;
}

/** The lab upload form and what is stored. */
export function SoftSensorLab({ sid, lab, originDefault, t }: LabProps) {
  const [text, setText] = useState("");
  const [origin, setOrigin] = useState(originDefault);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const chooseFile = (file: File | undefined) => {
    if (file === undefined) return;
    file.text().then(setText).catch(() => setError(t("soft.lab.readFailed")));
  };

  const upload = (event: React.FormEvent) => {
    event.preventDefault();
    const problem = checkLabText(text);
    if (problem !== null) return setError(t(`soft.lab.${problem}`));
    setBusy(true);
    setError(null);
    uploadSoftSensorLab(sid, { csvText: text, originIso: origin.trim() })
      .then(lab.set)
      .catch((failure: unknown) => setError(describeSoftError(failure, t)))
      .finally(() => setBusy(false));
  };

  return (
    <section aria-label={t("soft.lab.title")}>
      <h3>{t("soft.lab.title")}</h3>
      <p className="hint">{t("soft.lab.hint")}</p>
      <LabStored summary={lab.value} t={t} />
      {lab.error !== null && <p className="status status-error" role="alert">{lab.error}</p>}
      <form className="soft-lab-form" onSubmit={upload}>
        <label className="field">
          <span className="field-label">{t("soft.lab.text")}</span>
          <textarea className="field-input" rows={TEXT_ROWS} value={text} onChange={(event) => setText(event.target.value)} spellCheck={false} />
        </label>
        <label className="field">
          <span className="field-label">{t("soft.lab.file")}</span>
          <input className="field-input" type="file" accept=".csv,.txt,text/csv,text/plain" onChange={(event) => chooseFile(event.target.files?.[0])} />
        </label>
        <label className="field">
          <span className="field-label">{t("soft.lab.origin")}</span>
          <input className="field-input" type="text" value={origin} onChange={(event) => setOrigin(event.target.value)} />
        </label>
        <div className="toolbar">
          <button type="submit" disabled={busy || text.trim() === ""}>{busy ? t("soft.lab.uploading") : t("soft.lab.upload")}</button>
        </div>
      </form>
      {error !== null && <p className="status status-error" role="alert">{error}</p>}
    </section>
  );
}

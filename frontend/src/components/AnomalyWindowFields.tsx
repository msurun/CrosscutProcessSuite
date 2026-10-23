// Start and end of a window in hours from the start of the record, with the validation message
// below the fields. Shared by the fit form and the scan form of the Anomalies page.
import type { Translate } from "../findings";
import type { WindowCheck } from "../anomaly";

interface WindowFieldsProps {
  startText: string;
  endText: string;
  onStart: (text: string) => void;
  onEnd: (text: string) => void;
  check: WindowCheck;
  /** Record length in hours, named in the "beyond the record" message. */
  recordHours: number | null;
  t: Translate;
}

/** The two hour fields plus an alert with the first problem of the window, if any. */
export function AnomalyWindowFields({ startText, endText, onStart, onEnd, check, recordHours, t }: WindowFieldsProps) {
  const message = check.ok ? null : t(`anomaly.window.${check.error}`, { hours: recordHours === null ? "?" : recordHours.toFixed(2) });
  return (
    <>
      <label>
        {t("anomaly.window.start")}
        <input type="text" inputMode="decimal" value={startText} onChange={(event) => onStart(event.target.value)} aria-invalid={message !== null} />
      </label>
      <label>
        {t("anomaly.window.end")}
        <input type="text" inputMode="decimal" value={endText} onChange={(event) => onEnd(event.target.value)} aria-invalid={message !== null} />
      </label>
      {message !== null && <p className="status status-error" role="alert">{message}</p>}
    </>
  );
}

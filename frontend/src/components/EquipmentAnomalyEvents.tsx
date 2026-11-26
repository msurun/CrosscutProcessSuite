// Present runtime event evidence and audited user outcomes without inventing diagnoses.
// Signal shares are dimensionless; condition residuals use training standard deviations.
import type { EquipmentEvent, EquipmentOutcome } from "../equipmentAnomalyApi";
import type { Translate } from "../findings";

interface Props {
  event: EquipmentEvent;
  t: Translate;
  disabled: boolean;
  onOutcome: (event: EquipmentEvent, outcome: EquipmentOutcome) => void;
}
const OUTCOMES: EquipmentOutcome[] = ["real", "false_alarm", "maintenance_raised", "deferred"];
const PERCENT_PER_SHARE = 100; // Percent units per dimensionless contribution share.

/** Show event times, affected loops and ranked signal contributions as readable text. */
export function EquipmentEventEvidence({ event, t }: { event: EquipmentEvent; t: Translate }) {
  // The runtime supplies z = (observed - expected) / training deviation, not percent change.
  // Its EWMA sign describes the departure's direction, not a slope or a time-to-limit estimate.
  return <>
    <p>{event.opened_utc} — {event.closed_utc ?? t("equipmentAnomaly.open")}</p>
    <p>{t("equipmentAnomaly.peak", { value: event.peak })}</p>
    <p>{t("equipmentAnomaly.loops")}: {event.loops_affected.join(", ") || "—"}</p>
    <ul aria-label={t("equipmentAnomaly.contributions")}>
      {event.contributions.map((item) => <li key={item.tag}>{item.tag}: {(item.share * PERCENT_PER_SHARE).toFixed(1)} %</li>)}
    </ul>
    <ul aria-label={t("equipmentAnomaly.residuals")}>
      {event.residuals.map((item) => <li key={item.tag}>{item.tag}: {item.z.toFixed(2)} σ · {t(`equipmentAnomaly.trend.${Math.sign(item.trend)}`)}</li>)}
    </ul>
  </>;
}

/** Persist an explicit operator outcome; no default choice silently changes feedback. */
export function EquipmentEventHistory({ event, t, disabled, onOutcome }: Props) {
  return <details open>
    <summary>{event.opened_utc} · {t(`equipmentAnomaly.outcome.${event.outcome ?? "none"}`)}</summary>
    <EquipmentEventEvidence event={event} t={t} />
    <label className="field">{t("equipmentAnomaly.outcome")}
      <select data-testid={`outcome-${event.opened_utc}`} value={event.outcome ?? ""} disabled={disabled}
        onChange={(change) => { if (change.target.value) onOutcome(event, change.target.value as EquipmentOutcome); }}>
        <option value="">{t("equipmentAnomaly.outcome.none")}</option>
        {OUTCOMES.map((outcome) => <option key={outcome} value={outcome}>{t(`equipmentAnomaly.outcome.${outcome}`)}</option>)}
      </select>
    </label>
  </details>;
}

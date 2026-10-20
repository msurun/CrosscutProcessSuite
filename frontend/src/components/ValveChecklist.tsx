// Safety gate shown before the valve procedure. It lists the three checks an
// operator must confirm before continuing, and blocks the "continue" action
// until every box is ticked so the procedure is never started half-prepared.
import type { Translate } from "../findings";

interface ValveChecklistProps {
  /** Ticked state of each check, in display order: operator, manual, abort. */
  checks: [boolean, boolean, boolean];
  /** Called with the index of the checkbox the user just toggled. */
  onToggle: (index: 0 | 1 | 2) => void;
  /** Called when the user proceeds to the procedure. Only enabled when all are ticked. */
  onContinue: () => void;
  /** Called when the user goes back without starting the procedure. */
  onBack: () => void;
  /** Translation lookup shared across the app. */
  t: Translate;
}

/** Text keys for the three checks, in display order. */
const CHECK_KEYS = [
  "valve.check.operator",
  "valve.check.manual",
  "valve.check.abort",
] as const;

/**
 * Renders the pre-procedure safety checklist.
 *
 * The continue button stays disabled until all three boxes are ticked; the
 * component only reports state changes through its callbacks.
 */
export function ValveChecklist({
  checks,
  onToggle,
  onContinue,
  onBack,
  t,
}: ValveChecklistProps) {
  const isReady = checks.every((isTicked) => isTicked);

  return (
    <section className="valve-checklist" aria-labelledby="valve-checklist-title">
      <h3 id="valve-checklist-title">{t("valve.checklist.title")}</h3>
      <p>{t("valve.checklist.intro")}</p>
      <ul className="valve-checks">
        {CHECK_KEYS.map((checkKey, index) => (
          <li key={checkKey}>
            <label>
              <input
                type="checkbox"
                checked={checks[index as 0 | 1 | 2]}
                onChange={() => onToggle(index as 0 | 1 | 2)}
              />
              {t(checkKey)}
            </label>
          </li>
        ))}
      </ul>
      <button className="filter-chip" type="button" onClick={onBack}>
        {t("valve.checklist.back")}
      </button>
      <button
        className="filter-chip"
        type="button"
        onClick={onContinue}
        disabled={!isReady}
      >
        {t("valve.checklist.continue")}
      </button>
    </section>
  );
}

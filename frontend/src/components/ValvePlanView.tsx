// Renders the operator procedure of a valve stroke test plan: the ordered steps, a record hint,
// and the actions (back, print, record). The button row carries "no-print" so the print CSS
// hides it and the operator keeps only the procedure on paper.

import type { ValvePlan } from "../api";
import type { Translate } from "../findings";
import { procedureSentence } from "../valveTest";
import { formatFixed } from "../format";

/** Props of {@link ValvePlanView}. */
interface ValvePlanViewProps {
  /** The stroke test plan whose procedure is shown. */
  plan: ValvePlan;
  /** Called when the operator starts recording the test. */
  onRecord: () => void;
  /** Called to leave the plan view. */
  onBack: () => void;
  /** Translation function for the UI texts. */
  t: Translate;
}

/**
 * Show the operator procedure of a stroke test plan, step by step.
 *
 * The `<ol>` numbering is the step number, so each item carries only the sentence built from
 * the step code. The action buttons are hidden when the page is printed.
 */
export function ValvePlanView({ plan, onRecord, onBack, t }: ValvePlanViewProps) {
  const durationMinutes = plan.total_s / 60;
  return (
    <section className="valve-plan" aria-labelledby="valve-plan-title">
      <h3 id="valve-plan-title">{t("valve.plan.title")}</h3>
      <p>
        {t("valve.plan.summary", {
          steps: plan.n_steps,
          minutes: formatFixed(durationMinutes, 0),
        })}
      </p>
      <ol className="valve-procedure">
        {plan.procedure.map((step, index) => (
          <li key={index}>{procedureSentence(t, step)}</li>
        ))}
      </ol>
      <p>{t("valve.plan.recordHint")}</p>
      <div className="no-print">
        <button className="filter-chip" type="button" onClick={onBack}>
          {t("valve.plan.back")}
        </button>
        <button className="filter-chip" type="button" onClick={() => window.print()}>
          {t("valve.plan.print")}
        </button>
        <button className="filter-chip" type="button" onClick={onRecord}>
          {t("valve.plan.record")}
        </button>
      </div>
    </section>
  );
}

// Shared worklist explanation for historical and live loop rows.
// Keeps the backend's rank factors and first unresolved cause visible together with its action.

import { useState } from "react";

import type { Translate } from "../findings";
import {
  setFindingOutcome, type FindingOutcome, type FindingOutcomeInput, type LiveFinding,
} from "../liveLoopsApi";
import { actionText, diagnosisText, rankFactorsText, type WorklistDetails } from "../worklist";

/** Displays ranking evidence and the recommended action without deriving a second diagnosis. */
export function WorklistDetailsPanel({ details, t }: { details: WorklistDetails; t: Translate }) {
  return (
    <dl>
      <dt>{t("worklist.rank")}</dt>
      <dd>{rankFactorsText(t, details)}</dd>
      <dt>{t("worklist.diagnosisStep")}</dt>
      <dd>{diagnosisText(t, details.diagnosis_step)}</dd>
      <dt>{t("loops.column.action")}</dt>
      <dd>{actionText(t, details.next_action)}</dd>
    </dl>
  );
}

/** Outcome buttons of one finding (issue #150); the verdict is stored per loop, code and first-seen time. */
export function FindingOutcomeControls({
  loopId, finding, t, onSaved,
}: { loopId: string; finding: LiveFinding; t: Translate; onSaved: (outcome: FindingOutcome) => void }) {
  const [until, setUntil] = useState("");
  const [workOrder, setWorkOrder] = useState("");
  const [error, setError] = useState<string | null>(null);
  const save = (input: FindingOutcomeInput) => {
    setError(null);
    setFindingOutcome(loopId, finding, input)
      .then(() => onSaved(input.outcome))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  };
  // A deferral lasts until the end of the chosen local day.
  const deferInput = (): FindingOutcomeInput => ({ outcome: "deferred", until_utc: new Date(`${until}T23:59:59`).toISOString() });
  return (
    <fieldset className="finding-outcome" data-testid={`outcome-${finding.code}`}>
      <legend>{t("findingOutcome.legend", { code: finding.code })}</legend>
      {finding.outcome && <p className="status">{t(`findingOutcome.${finding.outcome}`)}</p>}
      <button type="button" onClick={() => save({ outcome: "fixed" })}>{t("findingOutcome.fixed")}</button>
      <button type="button" onClick={() => save({ outcome: "not_a_problem" })}>{t("findingOutcome.not_a_problem")}</button>
      <label>{t("findingOutcome.until")}
        <input type="date" value={until} onChange={(e) => setUntil(e.target.value)} />
      </label>
      <button type="button" disabled={until === ""} onClick={() => save(deferInput())}>{t("findingOutcome.deferred")}</button>
      <label>{t("findingOutcome.workOrder")}
        <input type="text" maxLength={64} value={workOrder} onChange={(e) => setWorkOrder(e.target.value)} />
      </label>
      <button type="button" onClick={() => save({ outcome: "maintenance_raised", ...(workOrder ? { work_order: workOrder } : {}) })}>
        {t("findingOutcome.maintenance_raised")}
      </button>
      {error && <p role="alert">{error}</p>}
    </fieldset>
  );
}

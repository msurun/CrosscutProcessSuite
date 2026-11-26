// Shared worklist explanation for historical and live loop rows.
// Keeps the backend's rank factors and first unresolved cause visible together with its action.

import type { Translate } from "../findings";
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

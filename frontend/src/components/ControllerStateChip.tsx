// Display the host record's state without implying an unreadable record is off.
// Shared by the controller list and detail so both explain an unknown state.

import type { ControllerSummary } from "../controllersApi";
import type { Translate } from "../findings";
import { stateLevel } from "./controllersFormat";
import { StatusChip } from "./StatusChip";

/** Show a problem chip when the host record cannot establish the controller state. */
export function ControllerStateChip({ row, t }: { row: ControllerSummary; t: Translate }) {
  const label = row.record_unreadable ? "controllers.recordUnreadable" : `controllers.state.${row.state}`;
  return <StatusChip level={row.record_unreadable ? "problem" : stateLevel(row.state)} label={t(label)} />;
}

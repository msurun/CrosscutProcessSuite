// frontend/src/components/GatewayLivenessCell.tsx
/**
 * Liveness of a controller as the write gateway sees it (ADR 015): the age of its last beat and,
 * when the gateway has declared the controller (or the whole runtime) lost, an alarm text.
 * Read-only: the gateway alone decides and releases the setpoints.
 */

import type { GatewayLiveness } from "../controllersApi";
import type { Translate } from "../findings";
import { StatusChip } from "./StatusChip";

export interface GatewayLivenessProps {
  id: string;
  liveness: GatewayLiveness | undefined;
  t: Translate;
}

function chipOf(liveness: GatewayLiveness | undefined, t: Translate) {
  const age = liveness?.age_s;
  if (!liveness || !liveness.known || age === null || age === undefined) {
    return <StatusChip level="unused" label={t("controllers.gwLiveness.unknown")} />;
  }
  const seconds = Math.round(age);
  if (liveness.lost) return <StatusChip level="problem" label={t("controllers.gwLiveness.lost", { seconds })} />;
  return <StatusChip level="ok" label={t("controllers.gwLiveness.ok", { seconds })} />;
}

export function GatewayLivenessCell({ id, liveness, t }: GatewayLivenessProps) {
  const alarm = liveness?.runtime_lost ? "controllers.gwLiveness.runtimeAlarm" : "controllers.gwLiveness.alarm";
  return (
    <div data-testid={`controller-gwliveness-${id}`}>
      {chipOf(liveness, t)}
      {liveness?.lost === true && (
        <p className="notice notice-warning" role="alert" data-testid={`controller-lost-${id}`}>{t(alarm, { id })}</p>
      )}
    </div>
  );
}

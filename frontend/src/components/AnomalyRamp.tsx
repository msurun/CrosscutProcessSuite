// Warning line of the Anomalies scan: tags whose window is mostly a long straight ramp (an
// interpolated archive gap), listed largest share first. Renders nothing when there are none.
import type { Translate } from "../findings";

interface RampProps {
  tags: Record<string, number> | undefined;
  t: Translate;
}

/** Tags sorted by share descending ("tag (NN %)"); ties keep the name order. */
function describeTags(tags: Record<string, number>): string {
  return Object.entries(tags)
    .sort(([nameA, shareA], [nameB, shareB]) => shareB - shareA || nameA.localeCompare(nameB))
    .map(([name, share]) => `${name} (${Math.round(share * 100)} %)`)
    .join(", ");
}

/** The warning for tags that carry no real measurement in the scanned window. */
export function AnomalyRamp({ tags, t }: RampProps) {
  if (tags === undefined || Object.keys(tags).length === 0) return null;
  return (
    <div className="status status-warning" role="status" data-testid="anomaly-ramp">
      {t("anomaly.ramp.body", { tags: describeTags(tags) })}
    </div>
  );
}

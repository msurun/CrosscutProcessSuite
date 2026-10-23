// Validity of the estimates of a run: a strip with the share of each class and a list with the
// counts and a plain-language explanation of each class. The strip is decoration (aria-hidden);
// the counts and percentages are always text, so nothing depends on colour or length.
import type { SoftSensorValidity } from "../api";
import type { Translate } from "../findings";
import { formatFixed } from "../format";
import { percentOf, UNRELIABLE, VALIDITY_ORDER } from "../softsensor";

const PERCENT_DECIMALS = 1;

/** The strip and the explained counts; `counts` are the numbers of estimates per class. */
export function SoftSensorValidityView({ counts, t }: { counts: Record<SoftSensorValidity, number>; t: Translate }) {
  const total = VALIDITY_ORDER.reduce((sum, kind) => sum + (counts[kind] ?? 0), 0);
  return (
    <section aria-label={t("soft.validity.title")} data-testid="soft-validity">
      <h3>{t("soft.validity.title")}</h3>
      <div className="validity-strip" aria-hidden="true">
        {VALIDITY_ORDER.map((kind) => (
          <span key={kind} className={`validity-segment validity-${kind}`} style={{ width: `${percentOf(counts[kind] ?? 0, total)}%` }} />
        ))}
      </div>
      <ul className="validity-list" aria-label={t("soft.validity.list")}>
        {VALIDITY_ORDER.map((kind) => (
          <li key={kind} data-testid={`validity-${kind}`}>
            <strong>{t(`soft.validity.${kind}`)}</strong>
            {": "}
            <span className="validity-count">{counts[kind] ?? 0}</span>
            {` (${formatFixed(percentOf(counts[kind] ?? 0, total), PERCENT_DECIMALS)} %)`}
            {UNRELIABLE.includes(kind) && (counts[kind] ?? 0) > 0 ? ` - ${t("soft.validity.doNotUse")}` : ""}
            <span className="hint validity-explain">{t(`soft.validity.${kind}.explain`)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

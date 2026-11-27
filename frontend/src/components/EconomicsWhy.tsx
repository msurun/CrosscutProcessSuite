// frontend/src/components/EconomicsWhy.tsx
/**
 * "Where and why" view of the MPC economic objective: the value, tracking and benefit rates of the
 * current target (currency/h) and the limits the target rests on, with the shadow price of each:
 * what relaxing that limit by one unit would earn per hour. Read-only.
 */

import type { MpcEconomicsDiagnostics } from "../controllersApi";
import type { Translate } from "../findings";
import { num } from "./MpcPanel";

export function EconomicsWhy({ economics, currency, t }: { economics?: MpcEconomicsDiagnostics; currency: string; t: Translate }) {
  if (!economics) return <p className="hint" data-testid="economics-why">{t("controllers.mpc.economics.noObjective")}</p>;
  const unit = `${currency}/h`;
  return (
    <div data-testid="economics-why">
      <h5>{t("controllers.mpc.economics.whyTitle")}</h5>
      <ul>
        <li>{t("controllers.mpc.economics.valueRate", { value: num(economics.value_rate), unit })}</li>
        <li>{t("controllers.mpc.economics.trackingRate", { value: num(economics.tracking_rate), unit })}</li>
        <li><strong>{t("controllers.mpc.economics.benefitRate", { value: num(economics.benefit_rate), unit })}</strong></li>
      </ul>
      {economics.binding.length === 0 ? (
        <p className="hint" data-testid="economics-binding-none">{t("controllers.mpc.economics.noBinding")}</p>
      ) : (
        <>
          <p className="hint">{t("controllers.mpc.economics.bindingExplain")}</p>
          <div className="table-scroll" tabIndex={0} role="region" aria-label={t("controllers.mpc.economics.bindingTitle")}>
            <table className="loops-table" data-testid="economics-binding">
              <caption className="hint">{t("controllers.mpc.economics.bindingTitle")}</caption>
              <thead>
                <tr>
                  <th scope="col">{t("controllers.col.variable")}</th>
                  <th scope="col">{t("controllers.mpc.economics.col.side")}</th>
                  <th scope="col">{t("controllers.mpc.economics.col.limit")}</th>
                  <th scope="col">{t("controllers.mpc.economics.col.shadow", { unit })}</th>
                </tr>
              </thead>
              <tbody>
                {economics.binding.map((b) => (
                  <tr key={`${b.kind}-${b.variable}-${b.side}-${b.limit}`}>
                    <th scope="row">{b.kind} {b.variable}</th>
                    <td>{t(`controllers.mpc.economics.side.${b.side}`)}</td>
                    <td>{t(`controllers.mpc.economics.limit.${b.limit}`)}</td>
                    <td>{num(b.shadow_price)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

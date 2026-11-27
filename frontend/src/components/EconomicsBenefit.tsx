// frontend/src/components/EconomicsBenefit.tsx
/**
 * Benefit report of the economic objective: replays the identified model twice (tracking-only and
 * economic) through POST /api/mpc/simulate/benefit and shows the gain in currency/h, the value
 * gained, the constraint violations of the economic branch (0 is good) and the share of time each
 * limit binds. Self-contained: limits come from the diagnostics, the artifact id is typed in.
 */

import { useState } from "react";
import type { FormEvent } from "react";
import type { ControllerDetail, MpcDiagnostics } from "../controllersApi";
import type { Translate } from "../findings";
import { simulateBenefit, type BenefitRequest, type BenefitResult, type SimulationLimits } from "../mpcSimulatorApi";
import { num } from "./MpcPanel";

/** Extra limit vectors the model-order request needs; comma-separated, one entry per variable. */
const EXTRA = ["priorities", "move_max", "rate_max", "target_rate", "funnel_start", "funnel_end"] as const;
const list = (text: string) => text.split(",").map((v) => Number(v.trim()));

/** Objective vectors in model order (diagnostic order of CVs and MVs); missing entries count as 0 / none. */
export function benefitRequest(
  detail: ControllerDetail, d: MpcDiagnostics, artifact: string, extra: Record<string, string>, steps: string,
): BenefitRequest {
  const e = detail.economics;
  const soft = (ids: string[], side: "lo" | "hi") => ids.map((id) => e?.soft_limits[id]?.[side] ?? null);
  const cvIds = d.cvs.map((c) => c.id);
  const mvIds = d.mvs.map((m) => m.id);
  const limits = {
    mv_lower: d.mvs.map((m) => m.lo), mv_upper: d.mvs.map((m) => m.hi),
    cv_lower: d.cvs.map((c) => c.lo), cv_upper: d.cvs.map((c) => c.hi),
    ...Object.fromEntries(EXTRA.map((k) => [k, list(extra[k] ?? "")])),
  } as SimulationLimits;
  return {
    artifact_id: artifact, controller_id: detail.id, limits, steps: Number(steps),
    settings: { prediction_horizon: 30, move_horizon: 5, move_suppression: 1 },
    economics: {
      cv_value: cvIds.map((id) => e?.cv_value[id] ?? 0), mv_cost: mvIds.map((id) => e?.mv_cost[id] ?? 0),
      cv_soft_lower: soft(cvIds, "lo"), cv_soft_upper: soft(cvIds, "hi"),
      mv_soft_lower: soft(mvIds, "lo"), mv_soft_upper: soft(mvIds, "hi"),
    },
  };
}

function Summary({ result, currency, t }: { result: BenefitResult; currency: string; t: Translate }) {
  const unit = `${currency}/h`;
  const violations = Object.values(result.economic.violations).reduce((n, v) => n + v.reduce((a, b) => a + b, 0), 0);
  const names = (kind: string, i: number) => (kind === "MV" ? result.mv_names : result.cv_names)[i] ?? String(i);
  return (
    <div data-testid="economics-benefit-result">
      <ul>
        <li><strong>{t("controllers.mpc.economics.benefitRate", { value: num(result.benefit_rate), unit })}</strong></li>
        <li>{t("controllers.mpc.economics.valueGained", { value: num(result.value_gained), currency })}</li>
        <li data-testid="economics-violations">
          {t("controllers.mpc.economics.violations", { n: violations })}{" "}
          {violations === 0 ? t("controllers.mpc.economics.violationsGood") : t("controllers.mpc.economics.violationsBad")}
        </li>
      </ul>
      <h5>{t("controllers.mpc.economics.bindingShare")}</h5>
      <ul data-testid="economics-benefit-binding">
        {(result.economic.binding ?? []).map((b) => (
          <li key={`${b.kind}-${b.index}-${b.side}-${b.limit}`}>
            {t("controllers.mpc.economics.shareLine", {
              name: `${b.kind} ${names(b.kind, b.index)}`, side: t(`controllers.mpc.economics.side.${b.side}`),
              limit: t(`controllers.mpc.economics.limit.${b.limit}`), pct: Math.round(b.share * 100),
            })}{" "}
            <progress max={1} value={b.share} aria-hidden="true" />
          </li>
        ))}
      </ul>
    </div>
  );
}

export function EconomicsBenefit({ detail, diagnostics, t }: { detail: ControllerDetail; diagnostics: MpcDiagnostics; t: Translate }) {
  const [artifact, setArtifact] = useState("");
  const [steps, setSteps] = useState("120");
  const [extra, setExtra] = useState<Record<string, string>>({ priorities: diagnostics.cvs.map(() => "1").join(", ") });
  const [result, setResult] = useState<BenefitResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function run(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(""); setResult(null);
    try { setResult(await simulateBenefit(benefitRequest(detail, diagnostics, artifact, extra, steps))); }
    catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
    finally { setBusy(false); }
  }
  return (
    <section data-testid="economics-benefit" aria-labelledby="economics-benefit-title">
      <h4 id="economics-benefit-title">{t("controllers.mpc.economics.benefitTitle")}</h4>
      <p className="hint">{t("controllers.mpc.economics.benefitHelp")}</p>
      <form onSubmit={(event) => void run(event)}>
        <fieldset disabled={busy}>
          <label className="field">{t("precommission.artifact_id")}
            <input required type="text" value={artifact} onChange={(e) => setArtifact(e.target.value)} />
          </label>
          <label className="field">{t("precommission.steps")}
            <input required type="number" step="1" value={steps} onChange={(e) => setSteps(e.target.value)} />
          </label>
          {EXTRA.map((k) => (
            <label className="field" key={k}>{t(`precommission.${k}`)}
              <input required type="text" value={extra[k] ?? ""} onChange={(e) => setExtra({ ...extra, [k]: e.target.value })} />
            </label>
          ))}
          <button type="submit" data-testid="economics-benefit-run">{t("controllers.mpc.economics.benefitRun")}</button>
        </fieldset>
      </form>
      {error && <p role="alert">{error}</p>}
      {busy && <p role="status">{t("precommission.running")}</p>}
      {result && <Summary result={result} currency={detail.economics?.currency ?? "currency"} t={t} />}
    </section>
  );
}

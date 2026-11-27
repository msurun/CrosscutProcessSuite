// Offline pre-commissioning comparison on a verified identified model.
// Only the simulation endpoint is called; controller and gateway state stay untouched.
import { useState } from "react";
import type { FormEvent } from "react";
import type { Translate } from "../findings";
import { LIMIT_FIELDS, simulateMpc, type SimulationLimits, type SimulationRequest, type SimulationResult } from "../mpcSimulatorApi";
import { INITIAL_FORM, SimulationFields, type SimulationForm } from "./PrecommissionFields";
import { PrecommissionResults } from "./PrecommissionResults";

/** Convert explicit form values into model-order engineering vectors and sample counts. */
function requestBody(form: SimulationForm): SimulationRequest {
  const limits = Object.fromEntries(LIMIT_FIELDS.map((key) =>
    [key, form.limits[key].split(",").map((value) => Number(value.trim()))])) as SimulationLimits;
  return {
    artifact_id: form.artifact_id, controller_id: form.controller_id, limits,
    pid_tunings: form.pid_tunings.map((row) => ({ loop_id: row.loop_id, kp: Number(row.kp),
      ti_s: Number(row.ti_s), td_s: Number(row.td_s), cv_index: Number(row.cv_index) })),
    settings: { prediction_horizon: Number(form.prediction_horizon), move_horizon: Number(form.move_horizon),
      move_suppression: Number(form.move_suppression) },
    scenario: { kind: form.kind as SimulationRequest["scenario"]["kind"], steps: Number(form.steps),
      step_at: Number(form.step_at), amplitude: Number(form.amplitude), cv_index: Number(form.cv_index),
      dv_index: Number(form.dv_index) },
  };
}

/** Submit a model-only comparison and clear stale results as soon as inputs change. */
export function PrecommissionPanel({ t }: { t: Translate }) {
  const [form, setForm] = useState(INITIAL_FORM);
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (next: SimulationForm) => { setForm(next); setResult(null); setError(""); };
  async function run(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(""); setResult(null);
    try { setResult(await simulateMpc(requestBody(form))); }
    catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
    finally { setBusy(false); }
  }
  return <section aria-label={t("precommission.title")}>
    <h3>{t("precommission.title")}</h3><p>{t("precommission.notice")}</p>
    <form onSubmit={(event) => void run(event)}><fieldset disabled={busy}>
      <SimulationFields form={form} set={set} t={t} />
      <button type="submit">{t(busy ? "precommission.running" : "precommission.run")}</button>
    </fieldset></form>
    {error && <p role="alert">{error}</p>}
    {busy && <p role="status">{t("precommission.running")}</p>}
    {result && <PrecommissionResults result={result} t={t} />}
  </section>;
}

// Form fields for an offline comparison with explicitly entered engineering limits.
// PID values are a current-tuning snapshot, paired with catalogue loops in MV order.
import type { Translate } from "../findings";
import { LIMIT_FIELDS } from "../mpcSimulatorApi";

interface PidEntry { loop_id: string; kp: string; ti_s: string; td_s: string; cv_index: string }

export interface SimulationForm {
  artifact_id: string; controller_id: string; kind: string;
  amplitude: string; steps: string; step_at: string; cv_index: string; dv_index: string;
  prediction_horizon: string; move_horizon: string; move_suppression: string;
  limits: Record<string, string>; pid_tunings: PidEntry[];
}
export const INITIAL_FORM: SimulationForm = {
  artifact_id: "", controller_id: "", kind: "sp_step", amplitude: "1", steps: "120", step_at: "5",
  cv_index: "0", dv_index: "0", prediction_horizon: "30", move_horizon: "5", move_suppression: "1",
  limits: Object.fromEntries(LIMIT_FIELDS.map((key) => [key, ""])),
  pid_tunings: [{ loop_id: "", kp: "", ti_s: "", td_s: "", cv_index: "0" }],
};
type FormProps = { form: SimulationForm; set: (form: SimulationForm) => void; t: Translate };
const SCALAR_FIELDS = ["artifact_id", "controller_id", "amplitude", "steps", "step_at", "cv_index",
  "dv_index", "prediction_horizon", "move_horizon", "move_suppression"] as const;

/** Labels keep units and zero-based model ordering visible beside each entry. */
export function SimulationFields({ form, set, t }: FormProps) {
  return <div className="knowledge-fields">
    <label className="field">{t("precommission.scenario")}
      <select value={form.kind} onChange={(event) => set({ ...form, kind: event.target.value })}>
        {["sp_step", "dv_step", "constraint_active"].map((kind) =>
          <option key={kind} value={kind}>{t(`precommission.${kind}`)}</option>)}
      </select>
    </label>
    {SCALAR_FIELDS.map((key) => <label className="field" key={key}>{t(`precommission.${key}`)}
      <input required type={key.endsWith("_id") ? "text" : "number"} step="any" value={form[key]}
        onChange={(event) => set({ ...form, [key]: event.target.value })} />
    </label>)}
    <LimitFields form={form} set={set} t={t} />
    <PidFields form={form} set={set} t={t} />
  </div>;
}

/** Vectors follow the identified model's CV and MV column ordering. */
function LimitFields({ form, set, t }: FormProps) {
  return <fieldset><legend>{t("precommission.limits")}</legend>
    <p>{t("precommission.vectorHint")}</p>
    {LIMIT_FIELDS.map((key) => <label className="field" key={key}>{t(`precommission.${key}`)}
      <input required value={form.limits[key]} onChange={(event) =>
        set({ ...form, limits: { ...form.limits, [key]: event.target.value } })} />
    </label>)}
  </fieldset>;
}

/** Enter the actual canonical PID snapshot rather than pretending the catalogue stores it. */
function PidFields({ form, set, t }: FormProps) {
  const update = (index: number, key: keyof PidEntry, value: string) => set({ ...form,
    pid_tunings: form.pid_tunings.map((row, position) => position === index
      ? { ...row, [key]: value } : row) });
  return <fieldset><legend>{t("precommission.pidSnapshot")}</legend>
    <p>{t("precommission.pidHint")}</p>
    {form.pid_tunings.map((row, index) => <fieldset key={index}><legend>MV {index + 1}</legend>
      {(["loop_id", "kp", "ti_s", "td_s", "cv_index"] as const).map((key) =>
        <label key={key} className="field">{t(`precommission.${key}`)}
          <input required type={key === "loop_id" ? "text" : "number"} step="any" value={row[key]}
            onChange={(event) => update(index, key, event.target.value)} />
        </label>)}
      <button type="button" disabled={form.pid_tunings.length === 1} onClick={() => set({ ...form,
        pid_tunings: form.pid_tunings.filter((_, position) => position !== index) })}>{t("precommission.remove")}</button>
    </fieldset>)}
    <button type="button" onClick={() => set({ ...form, pid_tunings: [...form.pid_tunings,
      { loop_id: "", kp: "", ti_s: "", td_s: "", cv_index: "0" }] })}>{t("precommission.add")}</button>
  </fieldset>;
}

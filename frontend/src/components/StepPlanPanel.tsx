// Multi-MV step-test planner (MPC 7.1a): preview, operator confirm, progress and abort.
// Steps leave only as normal gateway proposals in confirm mode; every one still needs approval.
import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../http";
import type { Translate } from "../findings";

interface MvRow { controller_id: string; variable_id: string; amplitude: string }
interface Settings {
  plan_type: "sequential" | "gbn"; duration_s: string; gap_s: string;
  sample_s: string; switch_probability: string; seed: string;
}
interface Step { index: number; mv: string; tag: string; at_s: number; value: number; status?: string }
interface Refusal { mv: string; code: string; step: number | null; detail: string }
interface Preview { ok: boolean; digest: string | null; steps: Step[]; refusals: Refusal[]; gateway_mode: string }
interface PlanRecord {
  id: string; status: string; steps: Step[]; abort_reason: string | null;
  displaced: { tag: string; baseline: number; last_applied: number }[];
}

const EMPTY_ROW: MvRow = { controller_id: "", variable_id: "", amplitude: "" };
const DEFAULTS: Settings = {
  plan_type: "sequential", duration_s: "", gap_s: "0", sample_s: "", switch_probability: "", seed: "0",
};
const ADVANCE_INTERVAL_MS = 5000; // Pace of the progress check while a plan runs.
const NUMBER_FIELDS = ["duration_s", "gap_s", "sample_s", "switch_probability", "seed"] as const;

/** The JSON body of preview and confirm, with numbers parsed from the form fields. */
function requestBody(settings: Settings, rows: MvRow[]) {
  const numbers = Object.fromEntries(NUMBER_FIELDS.map((key) => [key, Number(settings[key] || 0)]));
  return {
    ...numbers, plan_type: settings.plan_type,
    mvs: rows.map((row) => ({ ...row, amplitude: Number(row.amplitude) })),
  };
}

/** Send one JSON request through the authenticated client; throws the API's refusal text. */
async function send<T>(path: string, body?: unknown, method = "POST"): Promise<T> {
  const response = await apiFetch(`/api/mpc/step-plans${path}`, {
    method, headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await response.json() as { detail?: unknown } & T;
  if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : JSON.stringify(result.detail));
  return result;
}

/** Translate a stable code when the catalogue knows it, else show the raw code. */
function codeText(t: Translate, group: string, code: string): string {
  const key = `stepPlan.${group}.${code.split(":")[0]}`;
  const text = t(key);
  return text === key ? code : `${text}${code.includes(":") ? ` (${code.split(":")[1]})` : ""}`;
}

/** Poll a running plan: each tick resolves queued steps and proposes the next due one. */
function useProgress(plan: PlanRecord | null, setPlan: (plan: PlanRecord) => void, fail: (e: unknown) => void) {
  const id = plan?.status === "running" ? plan.id : null;
  useEffect(() => {
    if (id === null) return;
    const timer = window.setInterval(() => {
      send<PlanRecord>(`/${id}/advance`).then(setPlan).catch(fail);
    }, ADVANCE_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [id, setPlan, fail]);
}

function SettingsFields({ settings, onChange, t }: {
  settings: Settings; onChange: (settings: Settings) => void; t: Translate;
}) {
  const set = (key: keyof Settings, value: string) => onChange({ ...settings, [key]: value } as Settings);
  const gbn = settings.plan_type === "gbn";
  const shown: (keyof Settings)[] = ["duration_s", ...(gbn ? ["sample_s", "switch_probability", "seed"] as const : ["gap_s"] as const)];
  return <>
    <label className="field">{t("stepPlan.type")}
      <select value={settings.plan_type} onChange={(event) => set("plan_type", event.target.value)}>
        <option value="sequential">{t("stepPlan.type.sequential")}</option>
        <option value="gbn">{t("stepPlan.type.gbn")}</option>
      </select>
    </label>
    {shown.map((key) => (
      <label key={key} className="field">{t(`stepPlan.${key}`)}
        <input type="number" step="any" value={settings[key]}
          onChange={(event) => set(key, event.target.value)} />
      </label>
    ))}
  </>;
}

function MvRows({ rows, onChange, t }: { rows: MvRow[]; onChange: (rows: MvRow[]) => void; t: Translate }) {
  const set = (index: number, key: keyof MvRow, value: string) =>
    onChange(rows.map((row, i) => (i === index ? { ...row, [key]: value } : row)));
  return <>
    {rows.map((row, index) => (
      <fieldset key={index} className="toolbar">
        <legend>{t("stepPlan.mv", { n: index + 1 })}</legend>
        {(["controller_id", "variable_id", "amplitude"] as const).map((key) => (
          <label key={key} className="field">{t(`stepPlan.${key}`)}
            <input value={row[key]} type={key === "amplitude" ? "number" : "text"} step="any"
              onChange={(event) => set(index, key, event.target.value)} />
          </label>
        ))}
        <button type="button" disabled={rows.length === 1}
          onClick={() => onChange(rows.filter((_, i) => i !== index))}>{t("stepPlan.removeMv")}</button>
      </fieldset>
    ))}
    <button type="button" onClick={() => onChange([...rows, { ...EMPTY_ROW }])}>{t("stepPlan.addMv")}</button>
  </>;
}

function StepsTable({ steps, t }: { steps: Step[]; t: Translate }) {
  return <table>
    <caption>{t("stepPlan.schedule")}</caption>
    <thead><tr>
      <th scope="col">#</th><th scope="col">{t("stepPlan.col.mv")}</th>
      <th scope="col">{t("stepPlan.col.at")}</th><th scope="col">{t("stepPlan.col.value")}</th>
      <th scope="col">{t("stepPlan.col.status")}</th>
    </tr></thead>
    <tbody>{steps.map((step) => (
      <tr key={step.index}>
        <td>{step.index + 1}</td><td>{step.mv}</td><td>{step.at_s}</td><td>{step.value}</td>
        <td>{step.status ? codeText(t, "status", step.status) : ""}</td>
      </tr>
    ))}</tbody>
  </table>;
}

function Outcome({ preview, plan, t }: { preview: Preview | null; plan: PlanRecord | null; t: Translate }) {
  return <>
    {preview !== null && preview.refusals.length > 0 && <ul role="alert">
      {preview.refusals.map((row, index) => (
        <li key={index}>{row.mv} {codeText(t, "refusal", row.code)} {row.detail}</li>
      ))}
    </ul>}
    {plan === null && preview !== null && preview.steps.length > 0 && <StepsTable steps={preview.steps} t={t} />}
    {plan !== null && <>
      <p role="status">{t("stepPlan.state", { status: codeText(t, "status", plan.status) })}
        {plan.abort_reason && ` - ${codeText(t, "abort", plan.abort_reason)}`}</p>
      <StepsTable steps={plan.steps} t={t} />
      {plan.displaced.length > 0 && <p role="alert">{t("stepPlan.displaced")}{" "}
        {plan.displaced.map((d) => `${d.tag}: ${d.last_applied} (${t("stepPlan.baseline")} ${d.baseline})`).join("; ")}
      </p>}
    </>}
  </>;
}

/** The planner section: build, preview, confirm and follow a multi-MV step test. */
export function StepPlanPanel({ t }: { t: Translate }) {
  const [settings, setSettings] = useState(DEFAULTS);
  const [rows, setRows] = useState<MvRow[]>([{ ...EMPTY_ROW }]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [plan, setPlan] = useState<PlanRecord | null>(null);
  const [error, setError] = useState("");
  const fail = useCallback(
    (failure: unknown) => setError(failure instanceof Error ? failure.message : String(failure)), []);
  useProgress(plan, setPlan, fail);
  const body = requestBody(settings, rows);
  const filled = rows.every((row) => row.controller_id && row.variable_id && row.amplitude !== "") && settings.duration_s !== "";
  const run = (action: () => Promise<void>) => { setError(""); void action().catch(fail); };
  const running = plan?.status === "running";
  const canConfirm = preview?.ok === true && preview.gateway_mode === "confirm" && !running;
  return <section aria-label={t("stepPlan.title")}>
    <h3>{t("stepPlan.title")}</h3>
    <p>{t("stepPlan.notice")}</p>
    <SettingsFields settings={settings} onChange={(next) => { setSettings(next); setPreview(null); }} t={t} />
    <MvRows rows={rows} onChange={(next) => { setRows(next); setPreview(null); }} t={t} />
    <div className="toolbar">
      <button disabled={!filled || running} onClick={() => run(async () => {
        setPlan(null); setPreview(await send<Preview>("/preview", body));
      })}>{t("stepPlan.preview")}</button>
      <button disabled={!canConfirm} onClick={() => run(async () => {
        setPlan(await send<PlanRecord>("", { ...body, digest: preview?.digest }));
      })}>{t("stepPlan.confirm")}</button>
      <button disabled={!running} onClick={() => run(async () => {
        if (plan) setPlan(await send<PlanRecord>(`/${plan.id}/abort`));
      })}>{t("stepPlan.abort")}</button>
    </div>
    {preview !== null && preview.gateway_mode !== "confirm" && <p role="alert">{t("stepPlan.needConfirm")}</p>}
    {error !== "" && <p role="alert">{t("stepPlan.error", { reason: error })}</p>}
    <Outcome preview={preview} plan={plan} t={t} />
  </section>;
}

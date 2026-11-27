// frontend/src/components/EconomicsEditor.tsx
/**
 * Editor of the MPC economic objective (per hour): value per CV unit, cost per MV unit and the
 * soft (back-off) limits in engineering units. An empty field means "no entry". Save sends PUT,
 * Reset returns to the catalogue objective. Needs config.edit; the server answers the new detail.
 */

import { useState } from "react";
import {
  ControllersApiError, deleteControllerEconomics, putControllerEconomics,
  type ControllerDetail, type Economics,
} from "../controllersApi";
import type { Translate } from "../findings";

export const DEFAULT_CURRENCY = "currency";
type Draft = Record<string, string>;
const key = (field: string, id: string) => `${field}:${id}`;

function toDraft(economics: Economics | null | undefined): Draft {
  const draft: Draft = { currency: economics?.currency ?? "" };
  for (const [id, v] of Object.entries(economics?.cv_value ?? {})) draft[key("value", id)] = String(v);
  for (const [id, v] of Object.entries(economics?.mv_cost ?? {})) draft[key("cost", id)] = String(v);
  for (const [id, s] of Object.entries(economics?.soft_limits ?? {})) {
    if (s.lo !== undefined) draft[key("lo", id)] = String(s.lo);
    if (s.hi !== undefined) draft[key("hi", id)] = String(s.hi);
  }
  return draft;
}

/** Draft text to the request body; empty fields are omitted, not sent as 0. */
export function toBody(draft: Draft, cvs: string[], mvs: string[]): Economics {
  const num = (field: string, id: string) => {
    const text = (draft[key(field, id)] ?? "").trim();
    return text === "" ? undefined : Number(text);
  };
  const body: Economics = { cv_value: {}, mv_cost: {}, soft_limits: {} };
  if (draft.currency.trim() !== "") body.currency = draft.currency.trim();
  for (const id of cvs) { const v = num("value", id); if (v !== undefined) body.cv_value[id] = v; }
  for (const id of mvs) { const v = num("cost", id); if (v !== undefined) body.mv_cost[id] = v; }
  for (const id of [...cvs, ...mvs]) {
    const lo = num("lo", id);
    const hi = num("hi", id);
    if (lo !== undefined || hi !== undefined) {
      body.soft_limits[id] = { ...(lo !== undefined && { lo }), ...(hi !== undefined && { hi }) };
    }
  }
  return body;
}

interface RowsProps {
  title: string; ids: string[]; field: "value" | "cost"; draft: Draft; unit: string;
  set: (k: string, v: string) => void; disabled: boolean; t: Translate; testId: string;
}

function Rows({ title, ids, field, draft, unit, set, disabled, t, testId }: RowsProps) {
  const labels = {
    main: t(`controllers.mpc.economics.col.${field}`, { unit }),
    lo: t("controllers.mpc.economics.col.softLo"), hi: t("controllers.mpc.economics.col.softHi"),
  };
  const cell = (f: string, id: string, label: string) => (
    <input
      type="number" step="any" value={draft[key(f, id)] ?? ""} disabled={disabled}
      aria-label={`${id}: ${label}`} onChange={(e) => set(key(f, id), e.target.value)}
    />
  );
  return (
    <div className="table-scroll" tabIndex={0} role="region" aria-label={title}>
      <table className="loops-table" data-testid={testId}>
        <caption className="hint">{title}</caption>
        <thead>
          <tr>
            <th scope="col">{t("controllers.col.variable")}</th>
            <th scope="col">{labels.main}</th>
            <th scope="col">{labels.lo}</th>
            <th scope="col">{labels.hi}</th>
          </tr>
        </thead>
        <tbody>
          {ids.map((id) => (
            <tr key={id}>
              <th scope="row">{id}</th>
              <td>{cell(field, id, labels.main)}</td>
              <td>{cell("lo", id, labels.lo)}</td>
              <td>{cell("hi", id, labels.hi)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export interface EconomicsEditorProps {
  detail: ControllerDetail;
  canEdit: boolean;
  onSaved: (detail: ControllerDetail) => void;
  t: Translate;
}

function problemsOf(error: unknown): string[] {
  if (error instanceof ControllersApiError) return error.problems.length > 0 ? error.problems : [error.message];
  return [error instanceof Error ? error.message : String(error)];
}

export function EconomicsEditor({ detail, canEdit, onSaved, t }: EconomicsEditorProps) {
  const economics = detail.economics ?? null;
  const [draft, setDraft] = useState<Draft>(() => toDraft(economics));
  const [problems, setProblems] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const cvs = detail.variables.filter((v) => v.role === "CV").map((v) => v.id);
  const mvs = detail.variables.filter((v) => v.role === "MV").map((v) => v.id);
  const unit = `${draft.currency.trim() || DEFAULT_CURRENCY}/h`;
  const set = (k: string, v: string) => setDraft({ ...draft, [k]: v });

  async function run(action: () => Promise<ControllerDetail>, reload: boolean) {
    setBusy(true); setProblems([]);
    try {
      const next = await action();
      if (reload) setDraft(toDraft(next.economics));
      onSaved(next);
    } catch (error) { setProblems(problemsOf(error)); }
    finally { setBusy(false); }
  }

  return (
    <section data-testid="economics-editor" aria-labelledby="economics-title">
      <h4 id="economics-title">{t("controllers.mpc.economics.title")}</h4>
      <p className="hint">{t("controllers.mpc.economics.help")}</p>
      {economics && <p data-testid="economics-source">{t(`controllers.mpc.economics.source.${economics.source}`)}</p>}
      {!canEdit && <p className="hint" data-testid="economics-forbidden">{t("controllers.mpc.economics.forbidden")}</p>}
      <label className="field">{t("controllers.mpc.economics.currency")}
        <input type="text" value={draft.currency} disabled={!canEdit} onChange={(e) => set("currency", e.target.value)} />
      </label>
      <Rows title={t("controllers.mpc.economics.cvs")} ids={cvs} field="value" draft={draft} unit={unit} t={t}
        disabled={!canEdit} set={set} testId="economics-cvs" />
      <Rows title={t("controllers.mpc.economics.mvs")} ids={mvs} field="cost" draft={draft} unit={unit} t={t}
        disabled={!canEdit} set={set} testId="economics-mvs" />
      <div className="toolbar">
        <button type="button" data-testid="economics-save" disabled={!canEdit || busy}
          onClick={() => void run(() => putControllerEconomics(detail.id, toBody(draft, cvs, mvs)), false)}>
          {t("controllers.mpc.economics.save")}
        </button>{" "}
        <button type="button" data-testid="economics-reset" disabled={!canEdit || busy}
          onClick={() => void run(() => deleteControllerEconomics(detail.id), true)}>
          {t("controllers.mpc.economics.reset")}
        </button>
      </div>
      {problems.length > 0 && (
        <ul className="notice notice-warning" role="alert" data-testid="economics-error">
          {problems.map((line) => <li key={line}>{line}</li>)}
        </ul>
      )}
    </section>
  );
}

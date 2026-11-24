// Condition signals table and running-state form of one equipment (#214).
// Every proposal carries a confirmed checkbox so the engineer decides what the modules may use.
import type { ReactElement } from "react";
import type { Translate } from "../findings";
import { KINDS, type ConditionSignal, type Equipment, type RunningState } from "./equipmentModel";

export interface EquipmentSignalsProps {
  t: Translate;
  entry: Equipment;
  catalogueTags: string[];
  onChange: (patch: Partial<Equipment>) => void;
}

function RunningForm({ t, entry, onChange }: EquipmentSignalsProps): ReactElement {
  const run = entry.running;
  const candidates = (entry.signals ?? []).filter((s) => s.kind === "current" || s.kind === "speed");
  const set = (patch: Partial<RunningState>) =>
    onChange({ running: { tag: "", above: 0, confirmed: false, ...run, ...patch } });
  return (
    <fieldset>
      <legend>{t("equipment.running")}</legend>
      <select aria-label={t("equipment.runningTag")} value={run?.tag ?? ""} onChange={(e) => set({ tag: e.target.value })}>
        <option value="" />
        {candidates.map((s) => <option key={s.tag} value={s.tag}>{s.tag}</option>)}
      </select>
      <input
        type="number"
        aria-label={t("equipment.runningAbove")}
        value={run?.above ?? 0}
        onChange={(e) => set({ above: Number(e.target.value) })}
      />
      <label>
        <input type="checkbox" checked={run?.confirmed ?? false} onChange={(e) => set({ confirmed: e.target.checked })} />
        {t("equipment.runningConfirmed")}
      </label>
    </fieldset>
  );
}

function SignalRow(props: {
  t: Translate;
  signal: ConditionSignal;
  onEdit: (patch: Partial<ConditionSignal>) => void;
  onRemove: () => void;
}): ReactElement {
  const { t, signal: s, onEdit, onRemove } = props;
  return (
    <tr>
      <td>{s.tag}</td>
      <td>
        <select aria-label={t("equipment.kind", { tag: s.tag })} value={s.kind} onChange={(e) => onEdit({ kind: e.target.value })}>
          {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
      </td>
      <td>
        <input
          type="checkbox"
          aria-label={t("equipment.confirmedTag", { tag: s.tag })}
          checked={s.confirmed}
          onChange={(e) => onEdit({ confirmed: e.target.checked })}
        />
      </td>
      <td><button type="button" onClick={onRemove}>{t("equipment.removeSignal", { tag: s.tag })}</button></td>
    </tr>
  );
}

export function EquipmentSignals(props: EquipmentSignalsProps): ReactElement {
  const { t, entry, catalogueTags, onChange } = props;
  const signals = entry.signals ?? [];
  const edit = (i: number, patch: Partial<ConditionSignal>) =>
    onChange({ signals: signals.map((s, j) => (j === i ? { ...s, ...patch } : s)) });
  const free = catalogueTags.filter((tag) => !signals.some((s) => s.tag === tag));
  const add = (tag: string) =>
    tag && onChange({ signals: [...signals, { tag, kind: "context", confirmed: false }] });
  return (
    <section aria-label={t("equipment.signals")}>
      <h3>{t("equipment.signals")}</h3>
      <table>
        <tbody>
          {signals.map((s, i) => (
            <SignalRow key={s.tag} t={t} signal={s} onEdit={(p) => edit(i, p)}
              onRemove={() => onChange({ signals: signals.filter((_, j) => j !== i) })} />
          ))}
        </tbody>
      </table>
      <select aria-label={t("equipment.addSignal")} value="" onChange={(e) => add(e.target.value)}>
        <option value="">{t("equipment.addSignal")}</option>
        {free.map((tag) => <option key={tag} value={tag}>{tag}</option>)}
      </select>
      <RunningForm {...props} />
    </section>
  );
}

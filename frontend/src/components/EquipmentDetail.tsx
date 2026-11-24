// Detail form of the selected equipment entry (#214): name, criticality, parent and loops.
// Signals and running state are delegated to EquipmentSignals.
import type { ReactElement } from "react";
import type { Translate } from "../findings";
import { EquipmentSignals } from "./EquipmentSignals";
import { CRITICALITIES, ownedElsewhere, parentOptions, toggle, type Equipment } from "./equipmentModel";

export interface EquipmentDetailProps {
  t: Translate;
  list: Equipment[];
  entry: Equipment;
  catalogueLoops: string[];
  catalogueTags: string[];
  onChange: (patch: Partial<Equipment>) => void;
  onDelete: () => void;
}

function LoopList(props: { t: Translate; label: string; ids: string[]; all: string[]; onToggle: (id: string) => void }): ReactElement {
  const { t, label, ids, all, onToggle } = props;
  return (
    <fieldset>
      <legend>{label}</legend>
      {ids.map((id) => (
        <button key={id} type="button" onClick={() => onToggle(id)}>{t("equipment.removeLoop", { id })}</button>
      ))}
      <select aria-label={t("equipment.addLoop", { label })} value="" onChange={(e) => e.target.value && onToggle(e.target.value)}>
        <option value="">{t("equipment.add")}</option>
        {all.filter((id) => !ids.includes(id)).map((id) => <option key={id} value={id}>{id}</option>)}
      </select>
    </fieldset>
  );
}

export function EquipmentDetail(props: EquipmentDetailProps): ReactElement {
  const { t, list, entry, catalogueLoops, onChange } = props;
  const taken = ownedElsewhere(list, entry.id);
  return (
    <section aria-label={t("equipment.detail")}>
      <label>{t("equipment.name")}
        <input value={entry.name ?? ""} onChange={(e) => onChange({ name: e.target.value })} />
      </label>
      <label>{t("equipment.criticality")}
        <select value={entry.criticality ?? ""} onChange={(e) => onChange({ criticality: e.target.value || undefined })}>
          <option value="" />
          {CRITICALITIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </label>
      {entry.level !== "site" && (
        <label>{t("equipment.parent")}
          <select value={entry.parent ?? ""} onChange={(e) => onChange({ parent: e.target.value })}>
            {parentOptions(list, entry).map((p) => <option key={p.id} value={p.id}>{p.name || p.id}</option>)}
          </select>
        </label>
      )}
      <LoopList t={t} label={t("equipment.ownedLoops")} ids={entry.loops ?? []}
        all={catalogueLoops.filter((id) => !taken.has(id))} onToggle={(id) => onChange({ loops: toggle(entry.loops, id) })} />
      <LoopList t={t} label={t("equipment.referencedLoops")} ids={entry.loop_refs ?? []}
        all={catalogueLoops} onToggle={(id) => onChange({ loop_refs: toggle(entry.loop_refs, id) })} />
      <EquipmentSignals t={t} entry={entry} catalogueTags={props.catalogueTags} onChange={onChange} />
      <button type="button" onClick={props.onDelete}>{t("equipment.delete")}</button>
    </section>
  );
}

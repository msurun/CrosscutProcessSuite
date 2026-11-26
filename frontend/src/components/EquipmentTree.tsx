// Expandable tree of the equipment hierarchy (#214): counts of loops and signals, unconfirmed badge.
// Rendering only; selection and expansion state live in EquipmentEditor.
import type { ReactElement } from "react";
import type { Translate } from "../findings";
import { childrenOf, unconfirmedCount, type Equipment } from "./equipmentModel";

export interface EquipmentTreeProps {
  t: Translate;
  list: Equipment[];
  selected: string | null;
  collapsed: Set<string>;
  onSelect: (id: string) => void;
  onToggle: (id: string) => void;
}

function Row(props: EquipmentTreeProps & { entry: Equipment; depth: number }): ReactElement {
  const { t, list, selected, collapsed, onSelect, onToggle, entry, depth } = props;
  const kids = childrenOf(list, entry.id);
  const open = !collapsed.has(entry.id);
  const proposals = unconfirmedCount(entry);
  return (
    <li role="treeitem" aria-expanded={kids.length ? open : undefined} aria-selected={selected === entry.id}>
      <div style={{ paddingLeft: `${depth}rem`, display: "flex", gap: "0.4rem" }}>
        {kids.length > 0 && (
          <button type="button" aria-label={t("equipment.toggle", { id: entry.id })} onClick={() => onToggle(entry.id)}>
            {open ? "-" : "+"}
          </button>
        )}
        <button type="button" data-testid={`eq-${entry.id}`} onClick={() => onSelect(entry.id)}>
          {entry.name || entry.id}
        </button>
        <span>{t("equipment.counts", { loops: entry.loops?.length ?? 0, signals: entry.signals?.length ?? 0 })}</span>
        {proposals > 0 && <span className="badge">{t("equipment.unconfirmed", { count: proposals })}</span>}
      </div>
      {kids.length > 0 && open && (
        <ul role="group">{kids.map((k) => <Row key={k.id} {...props} entry={k} depth={depth + 1} />)}</ul>
      )}
    </li>
  );
}

export function EquipmentTree(props: EquipmentTreeProps): ReactElement {
  const ids = new Set(props.list.map((e) => e.id));
  const roots = props.list.filter((e) => !e.parent || !ids.has(e.parent));
  return (
    <ul role="tree" aria-label={props.t("equipment.tree")}>
      {roots.map((e) => <Row key={e.id} {...props} entry={e} depth={0} />)}
    </ul>
  );
}

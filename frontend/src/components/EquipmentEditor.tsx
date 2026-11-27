// Equipment hierarchy editor of the site catalogue (#214): tree, detail form, confirm proposals.
// Loads GET /api/site, edits the equipment list in memory and saves the whole document with PUT /api/site.
import { useEffect, useState, type ReactElement } from "react";
import { API_PREFIX, getJson, sendJson } from "../api";
import type { Translate } from "../findings";
import { EquipmentDetail } from "./EquipmentDetail";
import { EquipmentTree } from "./EquipmentTree";
import { addEntry, confirmAll, removeEntry, updateEntry, type Equipment, type SiteDoc } from "./equipmentModel";
import { DraftNotice } from "./DraftNotice";

export interface EquipmentEditorProps {
  t: Translate;
}

const SITE_URL = `${API_PREFIX}/site`;
const message = (e: unknown): string => (e instanceof Error ? e.message : String(e));

/** Site document state: loaded copy, edited equipment list, dirty flag. */
function useSite(setProblems: (text: string) => void) {
  const [site, setSite] = useState<SiteDoc | null>(null);
  const [list, setList] = useState<Equipment[]>([]);
  const [dirty, setDirty] = useState(false);
  const [drafted, setDrafted] = useState(false);
  useEffect(() => {
    getJson<SiteDoc>(SITE_URL)
      .then((doc) => { setSite(doc); setList(doc.equipment ?? []); })
      .catch((e) => setProblems(message(e)));
  }, [setProblems]);
  useEffect(() => {
    // Browser guard: closing the tab with unsaved edits asks for confirmation.
    const guard = (ev: BeforeUnloadEvent) => { if (dirty) ev.preventDefault(); };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [dirty]);
  const edit = (next: Equipment[]) => { setList(next); setDirty(true); };
  const save = async () => {
    try {
      await sendJson<unknown>("PUT", SITE_URL, { ...site, equipment: list });
      setSite({ ...site, equipment: list });
      setDirty(false);
      setDrafted(true);
      setProblems("");
    } catch (e) {
      setProblems(message(e));
    }
  };
  return { site, list, dirty, drafted, edit, save };
}

/** Which tree branches are collapsed. */
function useCollapsed(): [Set<string>, (id: string) => void] {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const flip = (id: string) => {
    const next = new Set(collapsed);
    if (!next.delete(id)) next.add(id);
    setCollapsed(next);
  };
  return [collapsed, flip];
}

export function EquipmentEditor({ t }: EquipmentEditorProps): ReactElement {
  const [problems, setProblems] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [collapsed, flip] = useCollapsed();
  const { site, list, dirty, drafted, edit, save } = useSite(setProblems);
  const entry = list.find((e) => e.id === selected) ?? null;
  const add = (level: "area" | "equipment") => {
    const next = addEntry(list, level, selected ?? undefined);
    if (!next) return setProblems(t("equipment.noParent"));
    edit(next);
    setSelected(next[next.length - 1].id);
  };
  const remove = () => {
    const next = entry && removeEntry(list, entry.id);
    if (!next) return setProblems(t("equipment.hasChildren"));
    edit(next), setSelected(null);
  };
  return (
    <section className="equipment-editor" aria-label={t("equipment.title")}>
      <div style={{ display: "flex", gap: "0.5rem" }}>
        <button type="button" onClick={() => add("area")}>{t("equipment.addArea")}</button>
        <button type="button" onClick={() => add("equipment")}>{t("equipment.addEquipment")}</button>
        <button type="button" onClick={() => edit(confirmAll(list))}>{t("equipment.confirmAll")}</button>
        <button type="button" onClick={save} disabled={!dirty}>{t("equipment.save")}</button>
      </div>
      {dirty && <p role="status">{t("equipment.unsaved")}</p>}
      {drafted && !dirty && <DraftNotice t={t} />}
      {problems && <pre role="alert">{problems}</pre>}
      {site && (
        <div style={{ display: "flex", gap: "1rem" }}>
          <EquipmentTree t={t} list={list} selected={selected} collapsed={collapsed} onSelect={setSelected} onToggle={flip} />
          {entry && (
            <EquipmentDetail t={t} list={list} entry={entry} onDelete={remove}
              catalogueLoops={(site.loops ?? []).map((l) => l.id)} catalogueTags={(site.tags ?? []).map((x) => x.id)}
              onChange={(patch) => edit(updateEntry(list, entry.id, patch))} />
          )}
        </div>
      )}
    </section>
  );
}

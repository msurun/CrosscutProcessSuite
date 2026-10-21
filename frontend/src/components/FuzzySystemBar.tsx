/**
 * System picker of the Fuzzy Studio page: choose a rule base, then save a copy under your own name.
 */

import { systemName } from "../fuzzyNames";
import { useEffect, useState } from "react";
import { saveFuzzySystem } from "../api";
import { slugify } from "../fuzzy";
import type { Translate } from "../findings";
import type { LibraryState } from "./FuzzyState";

interface SystemBarProps {
  library: LibraryState;
  t: Translate;
}

/** System picker: choose a rule base, then save a copy under a name of your own. */
export function SystemBar({ library, t }: SystemBarProps) {
  const [saveName, setSaveName] = useState("");
  const [isSaved, setIsSaved] = useState(false);

  const selected = library.systems.find((system) => system.id === library.selectedId);
  const defaultName = library.document === null
    ? ""
    : selected?.source === "user"
      ? selected.id
      : slugify(library.document.name);

  useEffect(() => {
    setSaveName(defaultName);
  }, [defaultName]);

  async function handleSave(): Promise<void> {
    if (library.document === null) return;
    const savedId = slugify(saveName);
    const saved = await saveFuzzySystem(savedId, library.document);
    await library.reloadLibrary();
    library.markSaved(saved);
    library.selectSystem(savedId === "" ? library.selectedId : savedId);
    setIsSaved(true);
  }

  return (
    <div className="toolbar">
      <label>
        {t("fuzzy.system")}
        <select value={library.selectedId} onChange={(event) => library.selectSystem(event.target.value)}>
          {library.systems.map((system) => (
            <option key={system.id} value={system.id}>
              {`${systemName(t, system.id, system.name)} (${t(`fuzzy.source.${system.source}`)})`}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("fuzzy.saveAs")}
        <input value={saveName} onChange={(event) => setSaveName(event.target.value)} />
      </label>
      <button type="button" onClick={() => void handleSave()}>
        {t("fuzzy.save")}
      </button>
      {library.isDirty && <span className="badge">{t("fuzzy.unsaved")}</span>}
      {isSaved && <span className="badge">{t("fuzzy.saved")}</span>}
    </div>
  );
}

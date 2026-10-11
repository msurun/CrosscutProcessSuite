/**
 * Fuzzy rule-base editor page: pick a system, edit it, try what-if values and replay it on a dataset.
 *
 * The page owns the edited document and the what-if input values; the backend recomputes the
 * inference (debounced) so the panels only have to draw the result.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchFuzzySystem,
  fetchFuzzySystems,
  inferFuzzy,
  saveFuzzySystem,
  type FuzzyInference,
  type FuzzySystemInfo,
} from "../api";
import type { FuzzyDocument } from "../fuzzy";
import { slugify } from "../fuzzy";
import type { Translate } from "../findings";
import { InferencePanel } from "./InferencePanel";
import { ReplayPanel } from "./ReplayPanel";
import { RulesEditor } from "./RulesEditor";
import { VersionsPanel } from "./VersionsPanel";
import { VariableEditor } from "./VariableEditor";

/** Delay before asking the backend for a new inference, so typing does not fire one call per key. */
const INFERENCE_DEBOUNCE_MS = 150;

/** Middle of `[low, high]`, the starting what-if value of an input. */
function middleValue(low: number, high: number): number {
  return (low + high) / 2;
}

/** One what-if value per input variable, all set to the middle of their range. */
function defaultInputValues(document: FuzzyDocument): Record<string, number> {
  const values: Record<string, number> = {};
  for (const variable of document.inputs) {
    values[variable.id] = middleValue(variable.low, variable.high);
  }
  return values;
}

/** The system to load first: the one already selected, otherwise the first of the list. */
function firstSystemId(systems: readonly FuzzySystemInfo[], selectedId: string): string {
  const selectedExists = systems.some((system) => system.id === selectedId);
  if (selectedId !== "" && selectedExists) return selectedId;
  return systems.length > 0 ? systems[0].id : "";
}

interface LibraryState {
  systems: FuzzySystemInfo[];
  selectedId: string;
  document: FuzzyDocument | null;
  savedJson: string;
  isDirty: boolean;
  loadError: string | null;
  saveCount: number;
  selectSystem: (systemId: string) => void;
  setDocument: (document: FuzzyDocument) => void;
  reloadLibrary: () => Promise<void>;
  markSaved: (document: FuzzyDocument) => void;
}

/**
 * Owns the system library and the loaded document.
 *
 * @returns The list of systems, the selected one, the edited document and the helpers to change them.
 */
function useFuzzyLibrary(t: Translate): LibraryState {
  const [systems, setSystems] = useState<FuzzySystemInfo[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [document, setDocumentState] = useState<FuzzyDocument | null>(null);
  const [savedJson, setSavedJson] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveCount, setSaveCount] = useState(0);

  const reloadLibrary = useCallback(async (): Promise<void> => {
    const list = await fetchFuzzySystems();
    setSystems(list);
  }, []);

  const selectSystem = useCallback((systemId: string): void => {
    setSelectedId(systemId);
  }, []);

  useEffect(() => {
    let isCancelled = false;
    async function loadSystem(): Promise<void> {
      if (selectedId === "") return;
      try {
        const loaded = await fetchFuzzySystem(selectedId);
        if (isCancelled) return;
        setDocumentState(loaded);
        setSavedJson(JSON.stringify(loaded));
        setLoadError(null);
      } catch (error) {
        if (isCancelled) return;
        setLoadError(error instanceof Error ? error.message : String(error));
      }
    }
    void loadSystem();
    return () => {
      isCancelled = true;
    };
  }, [selectedId]);

  useEffect(() => {
    let isCancelled = false;
    async function loadList(): Promise<void> {
      try {
        const list = await fetchFuzzySystems();
        if (isCancelled) return;
        setSystems(list);
        setSelectedId(firstSystemId(list, selectedId));
      } catch (error) {
        if (isCancelled) return;
        setLoadError(error instanceof Error ? error.message : String(error));
      }
    }
    void loadList();
    return () => {
      isCancelled = true;
    };
    // The list is read once on mount; later reloads go through reloadLibrary.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const markSaved = useCallback((document: FuzzyDocument): void => {
    setDocumentState(document);
    setSavedJson(JSON.stringify(document));
    setSaveCount((count) => count + 1);
  }, []);

  const isDirty = document !== null && JSON.stringify(document) !== savedJson;
  void t;
  return {
    systems,
    selectedId,
    document,
    savedJson,
    isDirty,
    loadError,
    saveCount,
    selectSystem,
    setDocument: setDocumentState,
    reloadLibrary,
    markSaved,
  };
}

interface WhatIfState {
  values: Record<string, number>;
  inference: FuzzyInference | null;
  error: string | null;
  setValues: (values: Record<string, number>) => void;
}

/**
 * Recomputes the inference for the current document and what-if values.
 *
 * The values are reset to the middle of each input range whenever a new document is loaded.
 *
 * @returns The current values, the last good inference and the last error message.
 */
function useWhatIf(document: FuzzyDocument | null): WhatIfState {
  const [values, setValues] = useState<Record<string, number>>({});
  const [inference, setInference] = useState<FuzzyInference | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (document === null) {
      setValues({});
      setInference(null);
      setError(null);
      return;
    }
    setValues(defaultInputValues(document));
    setInference(null);
    setError(null);
  }, [document]);

  useEffect(() => {
    if (document === null) return;
    let isCancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const result = await inferFuzzy(document, values);
        if (isCancelled) return;
        setInference(result);
        setError(null);
      } catch (failure) {
        if (isCancelled) return;
        setError(failure instanceof Error ? failure.message : String(failure));
      }
    }, INFERENCE_DEBOUNCE_MS);
    return () => {
      isCancelled = true;
      window.clearTimeout(timer);
    };
  }, [document, values]);

  return { values, inference, error, setValues };
}

interface SystemBarProps {
  library: LibraryState;
  t: Translate;
}

/** System picker: choose a rule base, then save a copy under a name of your own. */
function SystemBar({ library, t }: SystemBarProps) {
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
              {`${system.name} (${t(`fuzzy.source.${system.source}`)})`}
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

interface FuzzyPageProps {
  datasetId: string;
  t: Translate;
}

/**
 * Fuzzy rule-base screen.
 *
 * @param datasetId Dataset used by the replay panel; an empty string means no dataset is chosen.
 * @param t Translation function for the current language.
 */
export function FuzzyPage({ datasetId, t }: FuzzyPageProps) {
  const library = useFuzzyLibrary(t);
  const whatIf = useWhatIf(library.document);
  const replayKey = useMemo(() => library.document?.name ?? "", [library.document]);

  if (library.document === null) {
    return <p className="status">{t("trends.loading")}</p>;
  }

  return (
    <section>
      <header className="toolbar">
        <h2>{t("fuzzy.title")}</h2>
        <span className="badge">{t("fuzzy.advisory")}</span>
      </header>
      {library.document.description !== undefined && (
        <p className="hint">{library.document.description}</p>
      )}
      <SystemBar library={library} t={t} />
      {library.loadError !== null && (
        <p className="status status-error">{t("trends.error", { reason: library.loadError })}</p>
      )}
      {whatIf.error !== null && (
        <p className="status status-error">{t("trends.error", { reason: whatIf.error })}</p>
      )}
      <VariableEditor
        document={library.document}
        kind="inputs"
        onChange={library.setDocument}
        values={whatIf.values}
        degrees={whatIf.inference?.degrees}
        t={t}
      />
      <VariableEditor
        document={library.document}
        kind="outputs"
        onChange={library.setDocument}
        degrees={whatIf.inference?.degrees}
        t={t}
      />
      <RulesEditor
        document={library.document}
        onChange={library.setDocument}
        firing={whatIf.inference?.firing}
        t={t}
      />
      <InferencePanel
        document={library.document}
        values={whatIf.values}
        onValues={whatIf.setValues}
        inference={whatIf.inference}
        t={t}
      />
      <VersionsPanel
        systemId={library.selectedId}
        document={library.document}
        onRestore={library.setDocument}
        refreshKey={library.saveCount}
        t={t}
      />
      {datasetId !== "" ? (
        <ReplayPanel key={replayKey} datasetId={datasetId} document={library.document} t={t} />
      ) : (
        <p className="status">{t("fuzzy.dataset.none")}</p>
      )}
    </section>
  );
}

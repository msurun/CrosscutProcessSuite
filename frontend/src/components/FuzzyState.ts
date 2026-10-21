/**
 * State hooks of the Fuzzy Studio page: the system library with the loaded document, and the
 * debounced what-if inference. No drawing here; FuzzyPage composes them.
 */

import { useCallback, useEffect, useState } from "react";
import {
  fetchFuzzySystem,
  fetchFuzzySystems,
  inferFuzzy,
  type FuzzyInference,
  type FuzzySystemInfo,
} from "../api";
import type { FuzzyDocument } from "../fuzzy";
import type { Translate } from "../findings";

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

export interface LibraryState {
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
export function useFuzzyLibrary(t: Translate): LibraryState {
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

export interface WhatIfState {
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
export function useWhatIf(document: FuzzyDocument | null): WhatIfState {
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

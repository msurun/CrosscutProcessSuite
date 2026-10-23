// Data hooks of the Soft sensor page: the sensor list with the selected config, and the stored lab
// results and model of the selected sensor. Errors become text for the page (known cases get a
// translated message); late answers of an older request are dropped.
import { useCallback, useEffect, useState } from "react";
import {
  fetchSoftSensorConfig,
  fetchSoftSensorIds,
  fetchSoftSensorLab,
  fetchSoftSensorModel,
  saveSoftSensorConfig,
  type LabSummary,
  type SoftSensorConfig,
  type SoftSensorModelSummary,
} from "../api";
import type { Translate } from "../findings";
import { softErrorCode, type SoftErrorCode } from "../softsensor";
import exampleConfig from "../../../softsensor/examples/mill_circuit_pls.json";

/** The bundled example configuration (a copy of softsensor/examples/mill_circuit_pls.json). */
export const EXAMPLE_CONFIG = exampleConfig as SoftSensorConfig;

/** Message for any thrown value: a translated text for the known API cases, else the API message. */
export function describeSoftError(error: unknown, t: Translate): string {
  const code = softErrorCode(error);
  const detail = error instanceof Error ? error.message : String(error);
  return code === null ? detail : t(`soft.error.${code}`, { detail });
}

/** Sensors, the selected one and its config. */
export interface SoftSensorsState {
  ids: string[];
  loaded: boolean;
  selectedId: string;
  select: (id: string) => void;
  config: SoftSensorConfig | null;
  error: string | null;
  loadExample: () => Promise<void>;
}

/** Loads the sensor ids once; the first becomes selected; `loadExample` saves the bundled config. */
export function useSoftSensors(t: Translate): SoftSensorsState {
  const [ids, setIds] = useState<string[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [selectedId, select] = useState("");
  const [config, setConfig] = useState<SoftSensorConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async (preferred?: string) => {
    try {
      const found = await fetchSoftSensorIds();
      setIds(found);
      select((current) => preferred ?? (found.includes(current) ? current : (found[0] ?? "")));
      setError(null);
    } catch (failure: unknown) {
      setError(describeSoftError(failure, t));
    }
    setLoaded(true);
  }, [t]);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    setConfig(null);
    if (selectedId === "") return;
    let isCancelled = false;
    fetchSoftSensorConfig(selectedId)
      .then((loadedConfig) => !isCancelled && setConfig(loadedConfig))
      .catch((failure: unknown) => !isCancelled && setError(describeSoftError(failure, t)));
    return () => {
      isCancelled = true;
    };
  }, [selectedId, t]);

  const loadExample = useCallback(async () => {
    try {
      await saveSoftSensorConfig(EXAMPLE_CONFIG);
      await reload(EXAMPLE_CONFIG.id);
    } catch (failure: unknown) {
      setError(describeSoftError(failure, t));
    }
  }, [reload, t]);

  return { ids, loaded, selectedId, select, config, error, loadExample };
}

/** A value stored on the server: `null` while loading or when none exists; `set` after an upload or a fit. */
export interface StoredState<T> {
  value: T | null;
  loaded: boolean;
  error: string | null;
  set: (value: T) => void;
}

/** Loads a stored value of sensor `sid`; the "nothing stored yet" answer (`emptyCode`) is an empty state, not an error. */
function useStored<T>(sid: string, load: (sid: string) => Promise<T>, emptyCode: SoftErrorCode, t: Translate): StoredState<T> {
  const [value, set] = useState<T | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    set(null);
    setLoaded(false);
    setError(null);
    if (sid === "") return;
    let isCancelled = false;
    load(sid)
      .then((stored) => !isCancelled && set(stored))
      .catch((failure: unknown) => {
        if (!isCancelled && softErrorCode(failure) !== emptyCode) setError(describeSoftError(failure, t));
      })
      .finally(() => !isCancelled && setLoaded(true));
    return () => {
      isCancelled = true;
    };
  }, [sid, load, emptyCode, t]);

  return { value, loaded, error, set };
}

/** The stored lab results of `sid` (404 "no lab results" = none yet). */
export function useSoftLab(sid: string, t: Translate): StoredState<LabSummary> {
  return useStored(sid, fetchSoftSensorLab, "noLab", t);
}

/** The stored model of `sid` (404 "model not fitted" = none yet). */
export function useSoftModel(sid: string, t: Translate): StoredState<SoftSensorModelSummary> {
  return useStored(sid, fetchSoftSensorModel, "notFitted", t);
}

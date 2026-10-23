// Data hooks of the Anomalies page: the detector list with the selected config, and the stored
// model. Errors become text for the page (known cases get a translated message); late answers of
// an older request are dropped.
import { useCallback, useEffect, useState } from "react";
import {
  fetchAnomalyConfig,
  fetchAnomalyIds,
  fetchAnomalyModel,
  saveAnomalyConfig,
  type AnomalyConfig,
  type AnomalyModelSummary,
} from "../api";
import { anomalyErrorCode } from "../anomaly";
import type { Translate } from "../findings";
import exampleConfig from "../../../anomaly/examples/mill_circuit_pca.json";

/** The bundled example configuration (a copy of anomaly/examples/mill_circuit_pca.json). */
export const EXAMPLE_CONFIG = exampleConfig as AnomalyConfig;

/** Message for any thrown value: a translated text for the known API cases, else the API message. */
export function describeAnomalyError(error: unknown, t: Translate): string {
  const code = anomalyErrorCode(error);
  const detail = error instanceof Error ? error.message : String(error);
  return code === null ? detail : t(`anomaly.error.${code}`, { detail });
}

/** Detectors, the selected one and its config. */
export interface AnomaliesState {
  ids: string[];
  loaded: boolean;
  selectedId: string;
  select: (id: string) => void;
  config: AnomalyConfig | null;
  error: string | null;
  loadExample: () => Promise<void>;
}

/** Loads the detector ids once; the first becomes selected; `loadExample` saves the bundled config. */
export function useAnomalies(t: Translate): AnomaliesState {
  const [ids, setIds] = useState<string[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [selectedId, select] = useState("");
  const [config, setConfig] = useState<AnomalyConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async (preferred?: string) => {
    try {
      const found = await fetchAnomalyIds();
      setIds(found);
      select((current) => preferred ?? (found.includes(current) ? current : (found[0] ?? "")));
      setError(null);
    } catch (failure: unknown) {
      setError(describeAnomalyError(failure, t));
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
    fetchAnomalyConfig(selectedId)
      .then((loadedConfig) => !isCancelled && setConfig(loadedConfig))
      .catch((failure: unknown) => !isCancelled && setError(describeAnomalyError(failure, t)));
    return () => {
      isCancelled = true;
    };
  }, [selectedId, t]);

  const loadExample = useCallback(async () => {
    try {
      await saveAnomalyConfig(EXAMPLE_CONFIG);
      await reload(EXAMPLE_CONFIG.id);
    } catch (failure: unknown) {
      setError(describeAnomalyError(failure, t));
    }
  }, [reload, t]);

  return { ids, loaded, selectedId, select, config, error, loadExample };
}

/** The stored model of one detector: `null` while loading or when none is fitted; `set` after a fit. */
export interface ModelState {
  model: AnomalyModelSummary | null;
  loaded: boolean;
  error: string | null;
  set: (model: AnomalyModelSummary) => void;
}

/** Loads the model summary of `aid`; "not fitted" (404) is an empty state, not an error. */
export function useAnomalyModel(aid: string, t: Translate): ModelState {
  const [model, set] = useState<AnomalyModelSummary | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    set(null);
    setLoaded(false);
    setError(null);
    if (aid === "") return;
    let isCancelled = false;
    fetchAnomalyModel(aid)
      .then((summary) => !isCancelled && set(summary))
      .catch((failure: unknown) => {
        if (!isCancelled && anomalyErrorCode(failure) !== "notFitted") setError(describeAnomalyError(failure, t));
      })
      .finally(() => !isCancelled && setLoaded(true));
    return () => {
      isCancelled = true;
    };
  }, [aid, t]);

  return { model, loaded, error, set };
}

// Data hooks of the Advisory page: the supervisor list with the selected config, and the audit log.
// Errors become text for the page; late answers of an older request are dropped.
import { useCallback, useEffect, useState } from "react";
import {
  fetchAdvisoryLog,
  fetchSupervisorConfig,
  fetchSupervisors,
  saveSupervisorConfig,
  type AdvisoryLog,
  type SupervisorConfig,
} from "../api";
import exampleConfig from "../../../supervisor/examples/mill_feed_advisor.json";

/** The bundled example configuration (a copy of supervisor/examples/mill_feed_advisor.json). */
export const EXAMPLE_CONFIG = exampleConfig as SupervisorConfig;

/** Message text of any thrown value. */
export function describeError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Supervisors, the selected one and its config. */
export interface SupervisorsState {
  ids: string[];
  loaded: boolean;
  selectedId: string;
  select: (id: string) => void;
  config: SupervisorConfig | null;
  error: string | null;
  loadExample: () => Promise<void>;
}

/** Loads the supervisor ids once; the first becomes selected; `loadExample` saves the bundled config. */
export function useSupervisors(): SupervisorsState {
  const [ids, setIds] = useState<string[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [selectedId, select] = useState("");
  const [config, setConfig] = useState<SupervisorConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async (preferred?: string) => {
    try {
      const found = await fetchSupervisors();
      setIds(found);
      select((current) => preferred ?? (found.includes(current) ? current : (found[0] ?? "")));
      setError(null);
    } catch (failure: unknown) {
      setError(describeError(failure));
    }
    setLoaded(true);
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    setConfig(null);
    if (selectedId === "") return;
    let isCancelled = false;
    fetchSupervisorConfig(selectedId)
      .then((loadedConfig) => !isCancelled && setConfig(loadedConfig))
      .catch((failure: unknown) => !isCancelled && setError(describeError(failure)));
    return () => {
      isCancelled = true;
    };
  }, [selectedId]);

  const loadExample = useCallback(async () => {
    try {
      await saveSupervisorConfig(EXAMPLE_CONFIG);
      await reload(EXAMPLE_CONFIG.id);
    } catch (failure: unknown) {
      setError(describeError(failure));
    }
  }, [reload]);

  return { ids, loaded, selectedId, select, config, error, loadExample };
}

/** The log of one supervisor and a reload function; null while loading or when no supervisor is chosen. */
export function useAdvisoryLog(supervisorId: string): { log: AdvisoryLog | null; error: string | null; reload: () => void } {
  const [log, setLog] = useState<AdvisoryLog | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    setLog(null);
    if (supervisorId === "") return;
    let isCancelled = false;
    fetchAdvisoryLog(supervisorId)
      .then((loadedLog) => {
        if (isCancelled) return;
        setLog(loadedLog);
        setError(null);
      })
      .catch((failure: unknown) => !isCancelled && setError(describeError(failure)));
    return () => {
      isCancelled = true;
    };
  }, [supervisorId, attempt]);

  return { log, error, reload: () => setAttempt((count) => count + 1) };
}

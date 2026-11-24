// A link with `src=...&tags=...&start=...&end=...` reloads that plant window when its cache is gone (#202).
// Kept out of App.tsx; it navigates (replace) to the new cache id and keeps the query so the link stays valid.
import { useEffect, useRef } from "react";

import type { DatasetSummary } from "./api";
import { formatHash, type Route } from "./route";
import { loadHistory, parseHistoryQuery } from "./sourcesApi";
import type { Navigate } from "./useRoute";

/** True when `dataset` is a history cache of a catalogue source. */
function isHistoryCache(dataset: DatasetSummary | undefined): boolean {
  return dataset?.source.kind === "history";
}

/**
 * Loads the history named by the route query when the route's dataset is missing or not a history cache.
 * Each distinct link is tried once, so a failing source does not loop.
 */
export function useSourceReload(route: Route, datasets: DatasetSummary[], loaded: boolean, navigate: Navigate, refresh: () => void): void {
  const tried = useRef<string | null>(null);
  useEffect(() => {
    const request = parseHistoryQuery(route.query);
    const key = formatHash(route);
    if (!loaded || request === null || tried.current === key) return;
    if (isHistoryCache(datasets.find((one) => one.id === route.dataset))) return;
    tried.current = key;
    const range = { start_utc: request.start_utc, end_utc: request.end_utc };
    loadHistory(request.source, request.tags, range, request.period_s)
      .then((result) => {
        refresh();
        navigate({ ...route, dataset: result.dataset_id }, true);
      })
      .catch((error: unknown) => console.error("Failed to reload history from the link", error));
  }, [route, datasets, loaded, navigate, refresh]);
}

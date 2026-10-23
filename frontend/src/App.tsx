// src/App.tsx
import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchDatasets,
  fetchLoops,
  fetchTags,
  type DatasetSummary,
  type LoopSummary,
  type TagInfo,
} from "./api";
import { availableLanguages, detectLanguage, translate } from "./i18n";
import { ContextBar } from "./components/ContextBar";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { AdvisoryPage } from "./components/AdvisoryPage";
import { AnomalyPage } from "./components/AnomalyPage";
import { SoftSensorPage } from "./components/SoftSensorPage";
import { recordHours } from "./anomaly";
import { FuzzyPage } from "./components/FuzzyPage";
import { LoopsPage, type AnalysisInfo } from "./components/LoopsPage";
import { formatHash, withDataset, withView, type View } from "./route";
import { useRoute } from "./useRoute";
import { TagList } from "./components/TagList";
import { TopBar } from "./components/TopBar";
import { TrendsPage } from "./components/TrendsPage";
import { useTheme, type ThemePreference } from "./useTheme";

/** Language, its translator and the language setter, for the whole app. */
interface LanguageState {
  language: string;
  /** Translates `key` for the current language, filling `params` placeholders. */
  t: (key: string, params?: Record<string, string | number>) => string;
  setLanguage: (language: string) => void;
}

/** Loads the dataset catalogue on mount; `retry` loads it again after a failure. */
function useDatasets(): { datasets: DatasetSummary[]; failed: boolean; loaded: boolean; retry: () => void } {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let isCancelled = false;

    fetchDatasets()
      .then((result) => {
        if (isCancelled) return;
        setDatasets(result);
        setFailed(false);
        setLoaded(true);
      })
      .catch((error: unknown) => {
        console.error("Failed to load datasets", error);
        if (!isCancelled) setFailed(true);
      });

    return () => {
      isCancelled = true;
    };
  }, [attempt]);

  return { datasets, failed, loaded, retry: () => setAttempt((count) => count + 1) };
}

/** Loads the analysed loops of `datasetId` for grouping tags; a failure just means no grouping by loop. */
function useLoops(datasetId: string): LoopSummary[] {
  const [loops, setLoops] = useState<LoopSummary[]>([]);

  useEffect(() => {
    setLoops([]);
    if (datasetId === "") return;
    let isCancelled = false;
    fetchLoops(datasetId)
      .then((loaded) => {
        if (!isCancelled) setLoops(loaded);
      })
      .catch((error: unknown) => console.error("Failed to load loops", error));
    return () => {
      isCancelled = true;
    };
  }, [datasetId]);

  return loops;
}

/** Keeps the current language in sync with the browser and the document. */
function useLanguage(): LanguageState {
  const [language, setLanguage] = useState<string>(() =>
    detectLanguage(navigator.languages, availableLanguages()),
  );

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  // `t` only changes when the language changes, so memoising it is worthwhile.
  const t = useCallback(
    (key: string, params?: Record<string, string | number>) => translate(language, key, params),
    [language],
  );

  return { language, t, setLanguage };
}

/** Loads the tags of `datasetId`, or an empty list when no dataset is chosen. */
function useTags(datasetId: string): TagInfo[] {
  const [tags, setTags] = useState<TagInfo[]>([]);

  useEffect(() => {
    if (datasetId === "") {
      setTags([]);
      return;
    }
    let isCancelled = false;

    fetchTags(datasetId)
      .then((loaded) => {
        if (!isCancelled) {
          setTags(loaded);
        }
      })
      .catch((error: unknown) => {
        console.error("Failed to load tags", error);
      });

    return () => {
      isCancelled = true;
    };
  }, [datasetId]);

  return tags;
}

/** Root component: wires the data hooks, the layout and the trend panes. */
export function App() {
  const { datasets, failed, loaded, retry } = useDatasets();
  const { language, t, setLanguage } = useLanguage();
  const [theme, setTheme] = useTheme();
  const [route, navigate] = useRoute();
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [analysis, setAnalysis] = useState<AnalysisInfo | null>(null);
  const mainRef = useRef<HTMLElement>(null);
  const selectedDatasetId = route.dataset;
  const view = route.view;

  // No dataset in the URL: the first dataset of the catalogue becomes the default.
  useEffect(() => {
    if (selectedDatasetId === "" && datasets.length > 0) {
      navigate({ ...route, dataset: datasets[0].id }, true);
    }
  }, [datasets, selectedDatasetId, route, navigate]);

  // After the user navigates, focus moves to the content so keyboard and screen-reader users
  // start at the new page instead of at the top of the document.
  const previousHash = useRef(formatHash(route));
  useEffect(() => {
    const hash = formatHash(route);
    if (hash !== previousHash.current) mainRef.current?.focus();
    previousHash.current = hash;
  }, [route]);

  const tags = useTags(selectedDatasetId);
  const loops = useLoops(selectedDatasetId);
  const dataset = datasets.find((one) => one.id === selectedDatasetId);
  const datasetMissing = loaded && selectedDatasetId !== "" && dataset === undefined;

  // Selecting another dataset invalidates the tag selection of the old one.
  const handleDatasetChange = (datasetId: string) => {
    navigate(withDataset(route, datasetId));
    setSelectedTags([]);
  };

  const handleToggleTag = (tagId: string) => {
    setSelectedTags((previous) =>
      previous.includes(tagId) ? previous.filter((one) => one !== tagId) : [...previous, tagId],
    );
  };

  const themeNames: Record<ThemePreference, string> = {
    light: t("theme.light"),
    dark: t("theme.dark"),
    system: t("theme.system"),
  };

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content" onClick={(event) => { event.preventDefault(); mainRef.current?.focus(); }}>
        {t("a11y.skipToContent")}
      </a>
      <TopBar
        title={t("app.name")}
        readOnlyLabel={t("app.readOnly")}
        languages={availableLanguages()}
        language={language}
        onLanguage={setLanguage}
        languageLabel={t("top.language")}
        theme={theme}
        onTheme={setTheme}
        themeLabel={t("top.theme")}
        themeNames={themeNames}
      />
      <div className="app-body">
        <aside className="sidebar">
          <label className="field">
            <span className="field-label">{t("datasets.title")}</span>
            <select
              className="field-input"
              value={selectedDatasetId}
              onChange={(event) => handleDatasetChange(event.target.value)}
            >
              {datasets.map((dataset) => (
                <option key={dataset.id} value={dataset.id}>
                  {dataset.id}
                </option>
              ))}
            </select>
          </label>
          {view === "trends" && (
            <TagList
              tags={tags}
              selected={selectedTags}
              onToggle={handleToggleTag}
              searchLabel={t("trends.searchTags")}
              emptyLabel={t("trends.noTagsMatch")}
              loops={loops}
              otherLabel={t("trends.otherTags")}
            />
          )}
        </aside>
        <main className="main-area" id="main-content" tabIndex={-1} ref={mainRef}>
          {failed && (
            <div className="notice notice-warning" role="alert">
              <p>{t("error.apiOffline")}</p>
              <button type="button" className="filter-chip" onClick={retry}>
                {t("error.retry")}
              </button>
            </div>
          )}
          <ContextBar dataset={dataset} analysis={view === "loops" ? analysis : null} t={t} />
          <nav className="view-tabs" aria-label={t("app.name")}>
            {(["trends", "loops", "fuzzy", "advisory", "anomalies", "softsensor"] as const satisfies readonly View[]).map((name) => (
              <button
                key={name}
                type="button"
                className="view-tab"
                aria-current={view === name ? "page" : undefined}
                onClick={() => navigate(withView(route, name))}
              >
                {t(`nav.${name}`)}
              </button>
            ))}
          </nav>
          <ErrorBoundary t={t} resetKey={formatHash(route)}>
            {datasetMissing && (
              <p className="status status-error" role="alert">
                {t("route.notFoundDataset", { id: selectedDatasetId })}
              </p>
            )}
            {!datasetMissing && view === "loops" && selectedDatasetId && (
              <LoopsPage
                datasetId={selectedDatasetId}
                route={route}
                navigate={navigate}
                t={t}
                onAnalysed={setAnalysis}
              />
            )}
            {!datasetMissing && view === "advisory" && <AdvisoryPage datasetId={selectedDatasetId} t={t} />}
            {!datasetMissing && view === "anomalies" && (
              <AnomalyPage
                datasetId={selectedDatasetId}
                recordHours={dataset ? recordHours(dataset.time_range.start_utc, dataset.time_range.end_utc) : null}
                t={t}
              />
            )}
            {!datasetMissing && view === "softsensor" && (
              <SoftSensorPage
                datasetId={selectedDatasetId}
                recordHours={dataset ? recordHours(dataset.time_range.start_utc, dataset.time_range.end_utc) : null}
                startUtc={dataset ? dataset.time_range.start_utc : ""}
                t={t}
              />
            )}
            {!datasetMissing && view === "fuzzy" && <FuzzyPage datasetId={selectedDatasetId} t={t} />}
            {!datasetMissing && view === "trends" && (
              <TrendsPage datasetId={selectedDatasetId} tags={tags} selectedTags={selectedTags} t={t} />
            )}
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );

}

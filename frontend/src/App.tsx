// src/App.tsx
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  fetchDatasets,
  fetchSeries,
  fetchTags,
  type DatasetSummary,
  type Series,
  type TagInfo,
} from "./api";
import { availableLanguages, detectLanguage, translate } from "./i18n";
import { ContextBar } from "./components/ContextBar";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { FuzzyPage } from "./components/FuzzyPage";
import { LoopsPage, type AnalysisInfo } from "./components/LoopsPage";
import { formatHash, withDataset, withView, type View } from "./route";
import { useRoute } from "./useRoute";
import { TagList } from "./components/TagList";
import { TopBar } from "./components/TopBar";
import { TrendPane } from "./components/TrendPane";
import { anyDownsampled, toUplotData } from "./trendData";
import { useTheme, type ThemePreference } from "./useTheme";

/** Number of CSS series colour variables defined, cycled index % this. */
const SERIES_COLOR_COUNT = 7;
/** Maximum number of points the backend may return per series. */
const MAX_POINTS = 1500;
/** Height in pixels of every trend pane. */
const TREND_PANE_HEIGHT_PX = 260;

/** Lifecycle of the series request for the current dataset + tag selection. */
type Status = "idle" | "loading" | "error";

/** One trend pane: the tags that share a unit, plus the display metadata. */
interface UnitGroup {
  unit: string;
  series: Series[];
  labels: string[];
  colors: string[];
}

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

/** Loads the series of the selected tags, ignoring stale responses. */
function useSeries(
  datasetId: string,
  selectedTags: readonly string[],
): { series: Series[]; status: Status; errorReason: string } {
  const [series, setSeries] = useState<Series[]>([]);
  const [status, setStatus] = useState<Status>("idle");
  const [errorReason, setErrorReason] = useState<string>("");

  useEffect(() => {
    if (datasetId === "" || selectedTags.length === 0) {
      setSeries([]);
      setStatus("idle");
      setErrorReason("");
      return;
    }
    let isCancelled = false;
    setStatus("loading");

    fetchSeries(datasetId, selectedTags, { maxPoints: MAX_POINTS })
      .then((response) => {
        if (isCancelled) {
          return;
        }
        setSeries(response.series);
        setStatus("idle");
      })
      .catch((error: unknown) => {
        if (isCancelled) {
          return;
        }
        setSeries([]);
        setStatus("error");
        setErrorReason(error instanceof Error ? error.message : String(error));
      });

    return () => {
      isCancelled = true;
    };
  }, [datasetId, selectedTags]);

  return { series, status, errorReason };
}

/** Groups series by the unit of their tag, assigning colours in running order. */
function buildUnitGroups(series: readonly Series[], tags: readonly TagInfo[]): UnitGroup[] {
  const unitOfTag = new Map(tags.map((tag) => [tag.id, tag.unit ?? ""]));
  const groups = new Map<string, Series[]>();

  for (const one of series) {
    const unit = unitOfTag.get(one.tag) ?? "";
    const bucket = groups.get(unit) ?? [];
    bucket.push(one);
    groups.set(unit, bucket);
  }

  let colorIndex = 0;
  return [...groups].map(([unit, groupedSeries]) => {
    const labels = groupedSeries.map((one) => one.tag);
    const colors = groupedSeries.map(() => `--series-${(colorIndex++ % SERIES_COLOR_COUNT) + 1}`);
    return { unit, series: groupedSeries, labels, colors };
  });
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
  const { series, status, errorReason } = useSeries(selectedDatasetId, selectedTags);
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

  const unitGroups = useMemo(() => buildUnitGroups(series, tags), [series, tags]);
  const isDownsampled = anyDownsampled(series);
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
            {(["trends", "loops", "fuzzy"] as const satisfies readonly View[]).map((name) => (
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
            {!datasetMissing && view === "fuzzy" && <FuzzyPage datasetId={selectedDatasetId} t={t} />}
            {!datasetMissing && view === "trends" && renderTrendArea()}
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );

  /** Picks between the loading, error, empty and chart states of the main area. */
  function renderTrendArea() {
    if (status === "loading") {
      return <p className="status">{t("trends.loading")}</p>;
    }
    if (status === "error") {
      return <p className="status status-error">{t("trends.error", { reason: errorReason })}</p>;
    }
    if (selectedTags.length === 0) {
      return <p className="status">{t("trends.noData")}</p>;
    }
    return (
      <>
        {isDownsampled && <span className="badge">{t("trends.downsampled")}</span>}
        {unitGroups.map((group) => (
          <TrendPane
            timeLabel={t("trends.time")}
            key={group.unit}
            data={toUplotData(group.series)}
            labels={group.labels}
            colors={group.colors}
            unit={group.unit}
            height={TREND_PANE_HEIGHT_PX}
            syncKey="trends"
          />
        ))}
      </>
    );
  }
}

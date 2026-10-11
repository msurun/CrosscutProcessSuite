// src/App.tsx
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  fetchDatasets,
  fetchSeries,
  fetchTags,
  type DatasetSummary,
  type Series,
  type TagInfo,
} from "./api";
import { availableLanguages, detectLanguage, translate } from "./i18n";
import { LoopsPage } from "./components/LoopsPage";
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

/** Loads the dataset catalogue once on mount. */
function useDatasets(): { datasets: DatasetSummary[] } {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);

  useEffect(() => {
    let isCancelled = false;

    fetchDatasets()
      .then((loaded) => {
        if (!isCancelled) {
          setDatasets(loaded);
        }
      })
      .catch((error: unknown) => {
        console.error("Failed to load datasets", error);
      });

    return () => {
      isCancelled = true;
    };
  }, []);

  return { datasets };
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
  const { datasets } = useDatasets();
  const { language, t, setLanguage } = useLanguage();
  const [theme, setTheme] = useTheme();
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>("");
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [view, setView] = useState<"trends" | "loops">("trends");

  // The first dataset of the catalogue becomes the default selection.
  useEffect(() => {
    if (selectedDatasetId === "" && datasets.length > 0) {
      setSelectedDatasetId(datasets[0].id);
    }
  }, [datasets, selectedDatasetId]);

  const tags = useTags(selectedDatasetId);
  const { series, status, errorReason } = useSeries(selectedDatasetId, selectedTags);

  // Selecting another dataset invalidates the tag selection of the old one.
  const handleDatasetChange = (datasetId: string) => {
    setSelectedDatasetId(datasetId);
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
        <main className="main-area">
          <nav className="view-tabs" aria-label={t("app.name")}>
            {(["trends", "loops"] as const).map((name) => (
              <button
                key={name}
                type="button"
                className="view-tab"
                aria-current={view === name ? "page" : undefined}
                onClick={() => setView(name)}
              >
                {t(`nav.${name}`)}
              </button>
            ))}
          </nav>
          {view === "loops" ? (
            selectedDatasetId && <LoopsPage datasetId={selectedDatasetId} t={t} />
          ) : (
            renderTrendArea()
          )}
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

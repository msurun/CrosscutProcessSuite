// src/App.tsx
import { useCallback, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";

import {
  fetchDatasets,
  fetchLoops,
  fetchTags,
  type DatasetSummary,
  type LoopSummary,
  type TagInfo,
} from "./api";
import { availableLanguages, detectLanguage, translate } from "./i18n";
import { AuthProvider, useAuth } from "./AuthContext";
import { AuthGate } from "./AuthGate";
import { ContextBar } from "./components/ContextBar";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { type AnalysisInfo } from "./components/LoopsPage";
import { RoleBadge } from "./components/RoleBadge";
import { TagList } from "./components/TagList";
import { TopBar } from "./components/TopBar";
import { ViewContent } from "./components/ViewContent";
import { ViewTabs } from "./components/ViewTabs";
import { formatHash, withDataset, withView, type Route } from "./route";
import { useRoute } from "./useRoute";
import { useTheme, type ThemePreference } from "./useTheme";

/** Language, its translator and the language setter, for the whole app. */
interface LanguageState {
  language: string;
  /** Translates `key` for the current language, filling `params` placeholders. */
  t: (key: string, params?: Record<string, string | number>) => string;
  setLanguage: (language: string) => void;
}

/** Loads the dataset catalogue on mount; `retry` loads it again after a failure. */
function useDatasets(): { datasets: DatasetSummary[]; failed: boolean; loaded: boolean; retry: () => void; refresh: () => void } {
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

  const reload = useCallback(() => setAttempt((count) => count + 1), []);
  return { datasets, failed, loaded, retry: reload, refresh: reload };
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

type Navigate = (route: Route, replace?: boolean) => void;

/** Without a dataset in the URL the first dataset of the catalogue becomes the default. */
function useDefaultDataset(datasets: DatasetSummary[], route: Route, navigate: Navigate): void {
  useEffect(() => {
    if (route.dataset === "" && datasets.length > 0) {
      navigate({ ...route, dataset: datasets[0].id }, true);
    }
  }, [datasets, route, navigate]);
}

/** After the user navigates, focus moves to the content so keyboard users start at the new page. */
function useFocusOnNavigate(route: Route, mainRef: RefObject<HTMLElement>): void {
  const previousHash = useRef(formatHash(route));
  useEffect(() => {
    const hash = formatHash(route);
    if (hash !== previousHash.current) mainRef.current?.focus();
    previousHash.current = hash;
  }, [route, mainRef]);
}

/** Props of the shell: language state lives in `App` so the login page shares it. */
interface ShellProps {
  lang: LanguageState;
}

/** Header with the theme/language pickers and, when auth is on, the signed-in user badge. */
function ShellHeader({ lang, route, navigate }: ShellProps & { route: Route; navigate: Navigate }) {
  const { t } = lang;
  const [theme, setTheme] = useTheme();
  const { status } = useAuth();
  const themeNames: Record<ThemePreference, string> = {
    light: t("theme.light"),
    dark: t("theme.dark"),
    system: t("theme.system"),
  };
  return (
    <TopBar
      title={t("app.name")}
      readOnlyLabel={t("app.readOnly")}
      languages={availableLanguages()}
      language={lang.language}
      onLanguage={lang.setLanguage}
      languageLabel={t("top.language")}
      theme={theme}
      onTheme={setTheme}
      themeLabel={t("top.theme")}
      themeNames={themeNames}
      onCatalogue={() => navigate(withView(route, "catalogue"))}
      catalogueLabel={t("nav.catalogue")}
      account={status === "authenticated" ? <RoleBadge t={t} /> : undefined}
    />
  );
}

/** The "API offline" notice with a retry button. */
function ApiOffline({ retry, t }: { retry: () => void; t: LanguageState["t"] }) {
  return (
    <div className="notice notice-warning" role="alert">
      <p>{t("error.apiOffline")}</p>
      <button type="button" className="filter-chip" onClick={retry}>{t("error.retry")}</button>
    </div>
  );
}

interface SidebarProps {
  datasets: DatasetSummary[];
  route: Route;
  tags: TagInfo[];
  loops: LoopSummary[];
  selectedTags: string[];
  onDataset: (id: string) => void;
  onToggleTag: (id: string) => void;
  t: LanguageState["t"];
}

/** Dataset picker, plus the tag list while the trends view is open. */
function Sidebar(p: SidebarProps) {
  const { t } = p;
  return (
    <aside className="sidebar">
      <label className="field">
        <span className="field-label">{t("datasets.title")}</span>
        <select className="field-input" value={p.route.dataset} onChange={(event) => p.onDataset(event.target.value)}>
          {p.datasets.map((one) => (
            <option key={one.id} value={one.id}>{one.id}</option>
          ))}
        </select>
      </label>
      {p.route.view === "trends" && (
        <TagList tags={p.tags} selected={p.selectedTags} onToggle={p.onToggleTag} searchLabel={t("trends.searchTags")} emptyLabel={t("trends.noTagsMatch")} loops={p.loops} otherLabel={t("trends.otherTags")} />
      )}
    </aside>
  );
}

/** The signed-in application: header, dataset sidebar, tabs and the current page. */
function AppShell({ lang }: ShellProps) {
  const { t } = lang;
  const { datasets, failed, loaded, retry, refresh } = useDatasets();
  const [route, navigate] = useRoute();
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [analysis, setAnalysis] = useState<AnalysisInfo | null>(null);
  const mainRef = useRef<HTMLElement>(null);
  useDefaultDataset(datasets, route, navigate);
  useFocusOnNavigate(route, mainRef);
  const tags = useTags(route.dataset);
  const loops = useLoops(route.dataset);
  const dataset = datasets.find((one) => one.id === route.dataset);
  const datasetMissing = loaded && route.dataset !== "" && dataset === undefined;
  const changeDataset = (id: string) => {
    navigate(withDataset(route, id));
    setSelectedTags([]);
  };
  const toggleTag = (id: string) =>
    setSelectedTags((prev) => (prev.includes(id) ? prev.filter((one) => one !== id) : [...prev, id]));

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content" onClick={(event) => { event.preventDefault(); mainRef.current?.focus(); }}>
        {t("a11y.skipToContent")}
      </a>
      <ShellHeader lang={lang} route={route} navigate={navigate} />
      <div className="app-body">
        <Sidebar datasets={datasets} route={route} tags={tags} loops={loops} selectedTags={selectedTags} onDataset={changeDataset} onToggleTag={toggleTag} t={t} />
        <main className="main-area" id="main-content" tabIndex={-1} ref={mainRef}>
          {failed && <ApiOffline retry={retry} t={t} />}
          <ContextBar dataset={dataset} analysis={route.view === "loops" ? analysis : null} t={t} />
          <ViewTabs view={route.view} onSelect={(next) => navigate(withView(route, next))} t={t} />
          <ErrorBoundary t={t} resetKey={formatHash(route)}>
            {datasetMissing && <p className="status status-error" role="alert">{t("route.notFoundDataset", { id: route.dataset })}</p>}
            <ViewContent route={route} navigate={navigate} dataset={dataset} datasetMissing={datasetMissing} tags={tags} loops={loops} selectedTags={selectedTags} onAnalysed={setAnalysis} onDatasetCreated={refresh} t={t} />
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}

/** Root component: authentication around the shell (login, forced password change, session). */
export function App() {
  const lang = useLanguage();
  return (
    <AuthProvider t={lang.t}>
      <AuthGate t={lang.t}>
        <AppShell lang={lang} />
      </AuthGate>
    </AuthProvider>
  );
}

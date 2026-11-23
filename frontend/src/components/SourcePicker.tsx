// frontend/src/components/SourcePicker.tsx
// Left-panel picker: choose a catalogue source, tick its tags, pick a time window and a sampling period,
// then load the history into a cached dataset. Reports the HistoryResult through onLoaded.
import { useEffect, useMemo, useState } from "react";

import { ApiError } from "../api";
import type { Translate } from "../findings";
import { fetchSiteTags, listSources, loadHistory } from "../sourcesApi";
import type { CatalogueTag, HistoryResult, SiteSource } from "../sourcesApi";
import { NS_PER_MS, resolveWindow } from "../trendWindow";
import type { TrendWindow } from "../trendWindow";
import { TrendWindowBar } from "./TrendWindowBar";

/** Props of {@link SourcePicker}. */
export interface SourcePickerProps {
  t: Translate;
  onLoaded: (result: HistoryResult) => void;
}

/** Default window: the last 24 hours. */
const DEFAULT_WINDOW: TrendWindow = { kind: "relative", last_s: 86400 };
/** Sampling choices in seconds; 0 means raw samples (no period_s sent). */
const PERIODS_S = [0, 10, 60, 600];

/** Case-insensitive match of the search text against a tag's id, name and description. */
function matches(tag: CatalogueTag, search: string): boolean {
  const needle = search.trim().toLowerCase();
  if (!needle) return true;
  return [tag.id, tag.name, tag.description].some((s) => s?.toLowerCase().includes(needle));
}

/** Message of an error for display; ApiError carries the server detail. */
function messageOf(e: unknown): string {
  return e instanceof ApiError ? e.message : String(e);
}

/** Loads sources and catalogue tags once; `error` carries the failure message. */
function useCatalogue() {
  const [sources, setSources] = useState<SiteSource[]>([]);
  const [tags, setTags] = useState<CatalogueTag[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    Promise.all([listSources(), fetchSiteTags()])
      .then(([s, tg]) => {
        setSources(s.sources);
        setTags(tg);
      })
      .catch((e: unknown) => setError(messageOf(e)));
  }, []);
  return { sources, tags, error };
}

interface TagListProps {
  t: Translate;
  shown: CatalogueTag[];
  selected: Set<string>;
  search: string;
  onSearch: (value: string) => void;
  onSelected: (next: Set<string>) => void;
}

function TagList({ t, shown, selected, search, onSearch, onSelected }: TagListProps) {
  const toggle = (id: string) => {
    const next = new Set(selected);
    if (!next.delete(id)) next.add(id);
    onSelected(next);
  };
  return (
    <div>
      <input type="search" aria-label={t("sourcePicker.search")} value={search} onChange={(e) => onSearch(e.target.value)} />
      <button type="button" onClick={() => onSelected(new Set([...selected, ...shown.map((x) => x.id)]))}>
        {t("sourcePicker.selectAll")}
      </button>
      <button type="button" onClick={() => onSelected(new Set())}>
        {t("sourcePicker.clear")}
      </button>
      <span>{t("sourcePicker.selected", { count: selected.size })}</span>
      {shown.length === 0 && <p>{t("sourcePicker.noMatch")}</p>}
      <ul>
        {shown.map((tag) => (
          <li key={tag.id}>
            <label>
              <input type="checkbox" checked={selected.has(tag.id)} onChange={() => toggle(tag.id)} />
              {tag.id}
              {tag.name ? ` ${tag.name}` : ""}
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Resolve a window to ISO UTC start/end strings for the history request. */
function windowToIso(window: TrendWindow): { start: string; end: string } {
  const { startNs, endNs } = resolveWindow(window, Date.now());
  return { start: new Date(startNs / NS_PER_MS).toISOString(), end: new Date(endNs / NS_PER_MS).toISOString() };
}

/** Label of a sampling period option. */
function periodLabel(t: Translate, p: number): string {
  if (p === 0) return t("sourcePicker.periodRaw");
  return p >= 60 ? `${p / 60} min` : `${p} s`;
}

/** Runs the history load and tracks busy / cached / error state. */
function useHistoryLoader(onLoaded: (r: HistoryResult) => void) {
  const [busy, setBusy] = useState(false);
  const [cached, setCached] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (sourceId: string, tags: string[], window: TrendWindow, periodS: number) => {
    const { start, end } = windowToIso(window);
    setBusy(true);
    setError(null);
    try {
      const result = await loadHistory(sourceId, tags, { start_utc: start, end_utc: end }, periodS || undefined);
      setCached(result.cached);
      onLoaded(result);
    } catch (e) {
      setCached(false);
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  };
  return { busy, cached, error, run, resetCached: () => setCached(false) };
}

function PeriodSelect({ t, value, onChange }: { t: Translate; value: number; onChange: (p: number) => void }) {
  return (
    <label>
      {t("sourcePicker.period")}
      <select value={value} onChange={(e) => onChange(Number(e.target.value))}>
        {PERIODS_S.map((p) => (
          <option key={p} value={p}>
            {periodLabel(t, p)}
          </option>
        ))}
      </select>
    </label>
  );
}

function SourceSelect(props: { t: Translate; sources: SiteSource[]; value: string; onChange: (id: string) => void }) {
  return (
    <label>
      {props.t("sourcePicker.source")}
      <select value={props.value} onChange={(e) => props.onChange(e.target.value)}>
        <option value="" />
        {props.sources.map((s) => (
          <option key={s.id} value={s.id}>
            {s.id}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Source, tag, time window and sampling picker that loads history into a cached dataset. */
export function SourcePicker({ t, onLoaded }: SourcePickerProps) {
  const { sources, tags, error: catalogueError } = useCatalogue();
  const [sourceId, setSourceId] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [window, setWindow] = useState<TrendWindow>(DEFAULT_WINDOW);
  const [periodS, setPeriodS] = useState(0);
  const loader = useHistoryLoader(onLoaded);
  const sourceTags = useMemo(() => tags.filter((x) => x.source === sourceId), [tags, sourceId]);
  const shown = useMemo(() => sourceTags.filter((x) => matches(x, search)), [sourceTags, search]);
  const pickSource = (id: string) => {
    setSourceId(id);
    setSelected(new Set());
    loader.resetCached();
  };
  const shownError = loader.error ?? catalogueError;
  return (
    <section aria-label={t("sourcePicker.title")}>
      <h3>{t("sourcePicker.title")}</h3>
      {sources.length === 0 && !catalogueError && <p>{t("sourcePicker.noSources")}</p>}
      <SourceSelect t={t} sources={sources} value={sourceId} onChange={pickSource} />
      {sourceId && sourceTags.length === 0 && <p>{t("sourcePicker.noTags")}</p>}
      {sourceTags.length > 0 && (
        <TagList t={t} shown={shown} selected={selected} search={search} onSearch={setSearch} onSelected={setSelected} />
      )}
      <TrendWindowBar t={t} window={window} nowMs={Date.now()} onChange={setWindow} />
      <PeriodSelect t={t} value={periodS} onChange={setPeriodS} />
      <button
        type="button"
        disabled={!sourceId || selected.size === 0 || loader.busy}
        onClick={() => loader.run(sourceId, [...selected], window, periodS)}
      >
        {t("sourcePicker.load")}
      </button>
      <div role="status">{loader.busy ? t("sourcePicker.loading") : loader.cached ? t("sourcePicker.cached") : ""}</div>
      {shownError && <div role="alert">{shownError}</div>}
    </section>
  );
}

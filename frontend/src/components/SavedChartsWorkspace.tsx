// src/components/SavedChartsWorkspace.tsx
// The "Saved charts" side of the Trends view (#204-#207): the list of my and shared charts, the open
// chart with its time window, and the builder for a new or edited chart with a live preview.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { DatasetSummary, TagInfo } from "../api";
import { useAuth, useCan } from "../AuthContext";
import type { Translate } from "../findings";
import { formatHash } from "../route";
import { draftProblems, emptyDraft } from "../trendChartModel";
import { createChart, getChart, saveChart, type TrendChart, type TrendChartDraft } from "../trendChartsApi";
import { ChartBuilder } from "./ChartBuilder";
import { SavedChartsPanel } from "./SavedChartsPanel";
import { SavedChartView } from "./SavedChartView";
import { TrendWindowBar } from "./TrendWindowBar";

/** Id given to the unsaved chart drawn as the builder preview. */
const PREVIEW_ID = "preview00000";

interface WorkspaceProps {
  datasetId: string;
  dataset: DatasetSummary | undefined;
  tags: TagInfo[];
  t: Translate;
  /** Id of the chart named by the URL (`?chart=<id>`); it is opened when it differs from the open one. */
  chartId?: string | null;
  /** Called with the id of the chart that was opened or saved, so the URL can follow. */
  onChartChange?: (id: string) => void;
}

/** What the workspace shows: nothing yet, an open chart, or the builder for a draft. */
type Mode = { kind: "none" } | { kind: "view"; chart: TrendChart } | { kind: "edit"; draft: TrendChartDraft; base: TrendChart | null };

/** A draft drawn as if it were saved, so the preview uses the same view as an open chart. */
function previewOf(draft: TrendChartDraft): TrendChart {
  return { ...draft, schema_version: 1, id: PREVIEW_ID, owner: "", created_utc: "", updated_utc: "" };
}

/** Saves a draft: replaces the edited chart, or creates a new one. */
async function persist(draft: TrendChartDraft, base: TrendChart | null): Promise<TrendChart> {
  return base ? saveChart({ ...base, ...draft }) : createChart(draft);
}

/** Workspace state and the actions of its buttons; the open chart is mirrored to the URL through `onChartChange`. */
function useWorkspace(t: Translate, chartId: string | null, onChartChange?: (id: string) => void) {
  const [mode, setMode] = useState<Mode>({ kind: "none" });
  const [reloadToken, setReloadToken] = useState(0);
  const [error, setError] = useState("");
  const openedId = useRef<string | null>(null);
  const changeRef = useRef(onChartChange);
  changeRef.current = onChartChange;
  openedId.current = mode.kind === "view" ? mode.chart.id : null;
  const fail = (e: unknown) => setError(t("trendCharts.saveError", { reason: e instanceof Error ? e.message : String(e) }));
  const show = (chart: TrendChart) => {
    setMode({ kind: "view", chart });
    changeRef.current?.(chart.id);
  };
  const open = useCallback((id: string) => {
    setError("");
    getChart(id).then(show).catch(fail);
  }, []);
  // A chart named by the URL (shared link, "Open in Trends") is opened once; clicks already set the URL.
  useEffect(() => {
    if (chartId && chartId !== openedId.current) open(chartId);
  }, [chartId, open]);
  const save = (draft: TrendChartDraft, base: TrendChart | null) =>
    persist(draft, base)
      .then((chart) => {
        show(chart);
        setReloadToken((n) => n + 1);
      })
      .catch(fail);
  return { mode, setMode, reloadToken, error, open, save };
}

/** Builder, window bar and preview of a draft, with Save and Cancel. */
function EditPanel(props: { draft: TrendChartDraft; base: TrendChart | null; ws: WorkspaceProps; onDraft: (d: TrendChartDraft) => void; onSave: () => void; onCancel: () => void }) {
  const { ws, draft } = props;
  const valid = draftProblems(draft).length === 0 && draft.name.trim() !== "";
  const datasets = useMemo(() => (ws.dataset ? [ws.dataset] : []), [ws.dataset]);
  const preview = useMemo(() => previewOf(draft), [draft]);
  return (
    <section aria-label={ws.t("trendCharts.editTitle")}>
      <ChartBuilder t={ws.t} sourceId={ws.datasetId} tags={ws.tags} draft={draft} onChange={props.onDraft} />
      <TrendWindowBar t={ws.t} window={draft.window} nowMs={Date.now()} onChange={(window) => props.onDraft({ ...draft, window })} />
      <div className="trend-toolbar">
        <button type="button" onClick={props.onSave} disabled={!valid}>{ws.t("trendCharts.save")}</button>
        <button type="button" onClick={props.onCancel}>{ws.t("trendCharts.cancel")}</button>
      </div>
      {valid && <SavedChartView chart={preview} datasets={datasets} t={ws.t} />}
    </section>
  );
}

/** Copies the full URL of the open chart to the clipboard and confirms it. */
function CopyLinkButton(props: { datasetId: string; chartId: string; t: Translate }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    const hash = formatHash({ dataset: props.datasetId, view: "trends", loop: null, sub: "detail", query: { chart: props.chartId } });
    const url = `${window.location.origin}${window.location.pathname}${window.location.search}${hash}`;
    navigator.clipboard.writeText(url).then(() => setCopied(true)).catch(() => setCopied(false));
  };
  return (
    <>
      <button type="button" onClick={copy}>{props.t("trendCharts.copyLink")}</button>
      {copied && <span role="status">{props.t("trendCharts.linkCopied")}</span>}
    </>
  );
}

/** An open chart: its name, Edit for the owner, the window bar (not saved) and the panes. */
function ViewPanel(props: { chart: TrendChart; ws: WorkspaceProps; mine: boolean; onEdit: () => void; onWindow: (c: TrendChart) => void }) {
  const { chart, ws } = props;
  const datasets = useMemo(() => (ws.dataset ? [ws.dataset] : []), [ws.dataset]);
  return (
    <section aria-label={chart.name}>
      <h2>{chart.name}</h2>
      {props.mine && <button type="button" onClick={props.onEdit}>{ws.t("trendCharts.edit")}</button>}
      <CopyLinkButton datasetId={ws.datasetId} chartId={chart.id} t={ws.t} />
      <TrendWindowBar t={ws.t} window={chart.window} nowMs={Date.now()} onChange={(window) => props.onWindow({ ...chart, window })} />
      <SavedChartView chart={chart} datasets={datasets} t={ws.t} />
    </section>
  );
}

/** Splits a saved chart into the draft the builder edits. */
function draftOf(chart: TrendChart): TrendChartDraft {
  const { name, shared, series, axes, window, aggregation } = chart;
  return { name, shared, series, axes, window, aggregation };
}

/** The saved charts list beside the open chart or the builder. */
export function SavedChartsWorkspace(props: WorkspaceProps) {
  const { t } = props;
  const canShare = useCan("config.edit").allowed;
  const auth = useAuth();
  // Without auth the API stamps every chart with the local actor, so the caller owns them all.
  const me = auth.status === "disabled" ? null : (auth.user?.username ?? null);
  const ws = useWorkspace(t, props.chartId ?? null, props.onChartChange);
  const { mode, setMode } = ws;
  const activeId = mode.kind === "view" ? mode.chart.id : mode.kind === "edit" ? (mode.base?.id ?? null) : null;
  return (
    <div className="trend-workspace">
      <aside>
        <button type="button" onClick={() => setMode({ kind: "edit", draft: emptyDraft(t("trendCharts.newName")), base: null })}>{t("trendCharts.new")}</button>
        <SavedChartsPanel t={t} canShare={canShare} activeId={activeId} onOpen={ws.open} reloadToken={ws.reloadToken} />
      </aside>
      <div className="trend-workspace-main">
        {ws.error && <p className="status status-error" role="alert">{ws.error}</p>}
        {mode.kind === "none" && <p className="status">{t("trendCharts.pickOne")}</p>}
        {mode.kind === "view" && (
          <ViewPanel chart={mode.chart} ws={props} mine={me === null || mode.chart.owner === me} onEdit={() => setMode({ kind: "edit", draft: draftOf(mode.chart), base: mode.chart })} onWindow={(chart) => setMode({ kind: "view", chart })} />
        )}
        {mode.kind === "edit" && (
          <EditPanel draft={mode.draft} base={mode.base} ws={props} onDraft={(draft) => setMode({ ...mode, draft })} onSave={() => ws.save(mode.draft, mode.base)} onCancel={() => setMode(mode.base ? { kind: "view", chart: mode.base } : { kind: "none" })} />
        )}
      </div>
    </div>
  );
}

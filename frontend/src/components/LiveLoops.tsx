// src/components/LiveLoops.tsx
//
// The "Live" mode of the loops view: the catalogue loops the runtime analyses, with their findings
// (and since when), freshness, and a detail panel with the KPI and its history over time.
// `useLiveLoops` fetches the list every 30 s; no dataset is involved.

import { useCallback, useEffect, useState } from "react";

import { formatFixed } from "../format";
import { findingText, type Translate } from "../findings";
import { fetchLiveLoop, fetchLiveLoops, type LiveLoop, type LiveLoopDetail } from "../liveLoopsApi";
import { StatusChip } from "./StatusChip";
import { FindingOutcomeControls } from "./WorklistDetails";
import { TrendPane } from "./TrendPane";

/** How often the list is fetched again, in milliseconds. */
export const REFRESH_MS = 30_000;
/** KPI keys drawn over time: key, legend label key, series colour. */
const CHART_KEYS = [
  ["harris_index", "loops.harris", "--series-1"],
  ["saturation_fraction", "liveLoops.kpi.saturation", "--series-2"],
  ["flatline_fraction", "liveLoops.kpi.flatline", "--series-3"],
] as const;
/** Height of the history chart in pixels. */
const CHART_HEIGHT_PX = 160;
/** Column header keys of the worklist. */
const COLUMNS = ["loops.column.loop", "liveLoops.column.type", "loops.column.status", "loops.column.finding", "liveLoops.column.lastRun"];

/** Result of {@link useLiveLoops}: the list (null before the first answer) and the last error. */
export interface LiveLoopsState {
  loops: LiveLoop[] | null;
  error: string | null;
}

/** Fetches the live loops now and every REFRESH_MS; a failed refresh keeps the last list. */
export function useLiveLoops(): LiveLoopsState {
  const [state, setState] = useState<LiveLoopsState>({ loops: null, error: null });
  useEffect(() => {
    // A response that arrives after unmount must not set state.
    let isCancelled = false;
    const load = () =>
      fetchLiveLoops()
        .then((loops) => { if (!isCancelled) setState({ loops, error: null }); })
        .catch((e: unknown) => {
          if (!isCancelled) setState((old) => ({ loops: old.loops, error: e instanceof Error ? e.message : String(e) }));
        });
    void load();
    const timer = setInterval(load, REFRESH_MS);
    return () => { isCancelled = true; clearInterval(timer); };
  }, []);
  return state;
}

/** "5 minutes ago" in the page language; empty text for a missing or unparsable time. */
export function relativeTime(iso: string | null, now: number = Date.now()): string {
  const then = iso === null ? NaN : Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const seconds = Math.round((then - now) / 1000);
  const units: [Intl.RelativeTimeFormatUnit, number][] = [["day", 86400], ["hour", 3600], ["minute", 60]];
  const formatter = new Intl.RelativeTimeFormat(document.documentElement.lang || undefined, { numeric: "auto" });
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) return formatter.format(Math.round(seconds / size), unit);
  }
  return formatter.format(seconds, "second");
}

/** The KPI value under `key` when it is a finite number, else null. */
function num(kpi: Record<string, unknown> | null, key: string): number | null {
  const value = kpi?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** A share (0..1) of the KPI as a rounded percent, or undefined. */
function percentOf(kpi: Record<string, unknown> | null, key: string, invert = false): number | undefined {
  const share = num(kpi, key);
  if (share === null) return undefined;
  return Math.round((invert ? 1 - share : share) * 100);
}

/** Sentence of a finding; the runtime sends only the code, so the numbers are taken from the KPI. */
export function liveFindingText(t: Translate, code: string, kpi: Record<string, unknown> | null): string {
  const percents: Record<string, number | undefined> = {
    manual: percentOf(kpi, "service_factor", true),
    saturated: percentOf(kpi, "saturation_fraction"),
    flatline: percentOf(kpi, "flatline_fraction"),
  };
  const percent = percents[code];
  const period = num(kpi, "oscillation_period_s");
  const params: Record<string, number> = {};
  if (percent !== undefined) params.percent = percent;
  if (code === "oscillating" && period !== null) params.minutes = Math.round(period / 6) / 10;
  return findingText(t, { code, params });
}

/** Findings of one loop as a list, each with its "since" time. */
function FindingList({ loop, t }: { loop: LiveLoop; t: Translate }) {
  if (loop.findings.length === 0) return <span>{t("loops.noFindings")}</span>;
  return (
    <ul className="plain-list">
      {loop.findings.map((finding) => (
        <li key={finding.code}>
          {liveFindingText(t, finding.code, loop.kpi)}
          {finding.since_utc && <small> {t("liveLoops.since", { when: relativeTime(finding.since_utc) })}</small>}
        </li>
      ))}
    </ul>
  );
}

/** Status badge from the findings count; "no job" and "waiting" when nothing was measured. */
function LiveStatus({ loop, t }: { loop: LiveLoop; t: Translate }) {
  if (loop.job === null) return <StatusChip level="not_assessed" label={t("liveLoops.noJob")} />;
  if (loop.kpi === null) return <StatusChip level="not_assessed" label={t("liveLoops.waiting")} />;
  const level = loop.findings.length === 0 ? "ok" : "problem";
  return <StatusChip level={level} label={t(`status.${level}`)} />;
}

/** Last run cell: relative time plus the stale badge, or the hint for a loop without a job. */
function RunCell({ loop, t }: { loop: LiveLoop; t: Translate }) {
  if (loop.job === null) return <small>{t("liveLoops.noJobHint")}</small>;
  return (
    <>
      {relativeTime(loop.last_run_utc) || "-"}
      {!loop.fresh && <span className="badge badge-partial"> {t("liveLoops.stale")}</span>}
    </>
  );
}

/** One worklist row. */
function Row({ loop, selected, onSelect, t }: { loop: LiveLoop; selected: boolean; onSelect: () => void; t: Translate }) {
  return (
    <tr aria-selected={selected}>
      <th scope="row" className="cell-loop">
        <button type="button" className="link-button" onClick={onSelect}>{loop.name}</button>
      </th>
      <td>{loop.type ?? "-"}</td>
      <td><LiveStatus loop={loop} t={t} /> <ModeBadge loop={loop} t={t} /></td>
      <td><FindingList loop={loop} t={t} /></td>
      <td><RunCell loop={loop} t={t} /></td>
    </tr>
  );
}

/** Label/value pairs of the current KPI. */
function KpiList({ kpi, t }: { kpi: Record<string, unknown>; t: Translate }) {
  const share = (key: string) => (num(kpi, key) === null ? "-" : `${formatFixed(num(kpi, key)! * 100, 1)} %`);
  const harris = num(kpi, "harris_index");
  const rows: [string, string][] = [
    [t("liveLoops.kpi.service"), share("service_factor")],
    [t("liveLoops.kpi.saturation"), share("saturation_fraction")],
    [t("liveLoops.kpi.flatline"), share("flatline_fraction")],
    [t("loops.harris"), harris === null ? "-" : formatFixed(harris, 2)],
    [t("liveLoops.kpi.classification"), String(kpi.classification ?? "-")],
  ];
  return (
    <dl className="kv-list">
      {rows.map(([label, value]) => (
        <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
      ))}
    </dl>
  );
}

/** Badge with the operating mode of the newest sample and which samples the headline KPI uses. */
function ModeBadge({ loop, t }: { loop: LiveLoop; t: Translate }) {
  if (!loop.mode) return null;
  return (
    <span className="badge badge-partial" title={loop.kpi_scope ? t(`liveLoops.scope.${loop.kpi_scope}`) : undefined}>
      {t("liveLoops.modeBadge", { mode: loop.mode })}
    </span>
  );
}

/** KPI of every operating mode side by side; stopped samples are not part of any row. */
function ModeKpiTable({ byMode, t }: { byMode: Record<string, Record<string, unknown>>; t: Translate }) {
  const modes = Object.keys(byMode);
  if (modes.length === 0) return null;
  const share = (kpi: Record<string, unknown>, key: string) =>
    (num(kpi, key) === null ? "-" : `${formatFixed(num(kpi, key)! * 100, 1)} %`);
  return (
    <table className="loops-table">
      <caption>{t("liveLoops.byMode.caption")}</caption>
      <thead>
        <tr>
          <th scope="col">{t("liveLoops.byMode.mode")}</th>
          <th scope="col">{t("liveLoops.kpi.service")}</th>
          <th scope="col">{t("liveLoops.kpi.saturation")}</th>
          <th scope="col">{t("loops.harris")}</th>
          <th scope="col">{t("liveLoops.kpi.classification")}</th>
        </tr>
      </thead>
      <tbody>
        {modes.map((mode) => (
          <tr key={mode}>
            <th scope="row">{mode}</th>
            <td>{share(byMode[mode], "service_factor")}</td>
            <td>{share(byMode[mode], "saturation_fraction")}</td>
            <td>{num(byMode[mode], "harris_index") === null ? "-" : formatFixed(num(byMode[mode], "harris_index")!, 2)}</td>
            <td>{String(byMode[mode].classification ?? "-")}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** KPI over time: up to three numeric keys present in the history. */
function HistoryChart({ detail, t }: { detail: LiveLoopDetail; t: Translate }) {
  const keys = CHART_KEYS.filter(([key]) => detail.history.some((o) => num(o.kpi, key) !== null));
  if (detail.history.length < 2 || keys.length === 0) return <p className="status">{t("liveLoops.noHistory")}</p>;
  const times = detail.history.map((o) => Date.parse(o.utc) / 1000);
  const data = [times, ...keys.map(([key]) => detail.history.map((o) => num(o.kpi, key)))];
  return (
    <TrendPane
      data={data}
      labels={keys.map(([, label]) => t(label))}
      colors={keys.map(([, , color]) => color)}
      height={CHART_HEIGHT_PX}
      syncKey="live-loops"
      t={t}
    />
  );
}

/** The detail panel of the selected loop: KPI, findings and history (fetched again after each run). */
function LiveDetail({ loop, t }: { loop: LiveLoop; t: Translate }) {
  const [detail, setDetail] = useState<LiveLoopDetail | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const reload = useCallback(() => {
    fetchLiveLoop(loop.id).then(setDetail).catch(() => setDetail(null));
  }, [loop.id]);
  useEffect(reload, [reload, loop.last_run_utc]);
  return (
    <section aria-label={t("liveLoops.detail", { name: loop.name })}>
      <h3>{loop.name} <ModeBadge loop={loop} t={t} /></h3>
      {loop.kpi ? <KpiList kpi={loop.kpi} t={t} /> : <p className="status">{t("liveLoops.waiting")}</p>}
      {loop.by_mode && <ModeKpiTable byMode={loop.by_mode} t={t} />}
      <FindingList loop={loop} t={t} />
      {loop.findings.map((finding) => (
        <FindingOutcomeControls key={`${finding.code}|${finding.since_utc}`} loopId={loop.id} finding={finding} t={t}
          onSaved={(outcome) => setSaved(t("findingOutcome.saved", { outcome: t(`findingOutcome.${outcome}`) }))} />
      ))}
      {saved && <p className="status" role="status">{saved}</p>}
      {detail && <HistoryChart detail={detail} t={t} />}
      <p className="hint">{t("liveLoops.pastWindowHint")}</p>
    </section>
  );
}

/** The live worklist and, below it, the detail of the selected loop. */
export function LiveLoops({ loops, t }: { loops: LiveLoop[]; t: Translate }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  if (loops.length === 0) return <p className="status">{t("liveLoops.empty")}</p>;
  const selected = loops.find((loop) => loop.id === selectedId) ?? null;
  return (
    <div data-testid="live-loops">
      <div className="table-scroll">
        <table className="loops-table">
          <thead>
            <tr>{COLUMNS.map((key) => <th scope="col" key={key}>{t(key)}</th>)}</tr>
          </thead>
          <tbody>
            {loops.map((loop) => (
              <Row key={loop.id} loop={loop} selected={loop.id === selectedId} onSelect={() => setSelectedId(loop.id)} t={t} />
            ))}
          </tbody>
        </table>
      </div>
      {selected && <LiveDetail loop={selected} t={t} />}
    </div>
  );
}

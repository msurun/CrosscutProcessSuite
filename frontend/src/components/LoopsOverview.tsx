// src/components/LoopsOverview.tsx
//
// The loop worklist: which loops need attention, why, and what to do next. Rows follow the
// backend's priority order by default; the user can filter by status, search, and re-sort.

import { useMemo, useState } from "react";
import type { LoopStatus, LoopSummary } from "../api";
import { formatPercent } from "../format";
import { StatusChip } from "./StatusChip";
import { Sparkline } from "./Sparkline";
import { mainFindingText, type Translate } from "../findings";
import {
  DEFAULT_QUERY,
  actionText,
  applyQuery,
  ariaSort,
  isPartiallyAssessed,
  nextSort,
  withheldText,
  worklistCsv,
  type OverviewQuery,
  type SortKey,
} from "../worklist";

/** Every status the overview can display, in the order of the filter bar. */
const STATUS_ORDER: LoopStatus[] = ["problem", "warning", "not_assessed", "ok", "unused"];

/** CSV file name offered by the export button. */
const EXPORT_FILE_NAME = "loop-worklist.csv";

/** The translation key that shows the human-readable name of a status. */
function statusLabelKey(status: LoopStatus): string {
  return `status.${status}`;
}

/**
 * Counts how many loops carry each status.
 * Statuses that do not occur are absent from the returned record.
 */
export function countByStatus(loops: LoopSummary[]): Partial<Record<LoopStatus, number>> {
  const counts: Partial<Record<LoopStatus, number>> = {};
  for (const loop of loops) {
    counts[loop.status] = (counts[loop.status] ?? 0) + 1;
  }
  return counts;
}

/** A loop needs attention when it is broken or degraded. */
function needsAttention(loop: LoopSummary): boolean {
  return loop.status === "problem" || loop.status === "warning";
}

/** Health as "70 %" (the column header already says "Health"), or an en dash when unknown. */
function formatHealth(loop: LoopSummary): string {
  return loop.health_percent === null ? "–" : formatPercent(loop.health_percent);
}

/** Offers the worklist as a CSV download; the file is built in the browser, nothing is uploaded. */
function downloadCsv(loops: LoopSummary[], t: Translate): void {
  const blob = new Blob(["﻿" + worklistCsv(loops, t)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = EXPORT_FILE_NAME;
  link.click();
  URL.revokeObjectURL(url);
}

/** One filter button. `pressed` is the aria-pressed value, hence the name. */
function FilterButton({ label, pressed, onClick }: { label: string; pressed: boolean; onClick: () => void }) {
  return (
    <button type="button" className="filter-chip" aria-pressed={pressed} onClick={onClick}>
      {label}
    </button>
  );
}

/** Status filter buttons: "All" plus one per occurring status, each with its count. */
function FilterBar({
  counts,
  total,
  selected,
  onSelect,
  t,
}: {
  counts: Partial<Record<LoopStatus, number>>;
  total: number;
  selected: LoopStatus | "all";
  onSelect: (filter: LoopStatus | "all") => void;
  t: Translate;
}) {
  const presentStatuses = STATUS_ORDER.filter((status) => counts[status] !== undefined);
  return (
    <div className="loops-filters" role="group" aria-label={t("loops.column.status")}>
      <FilterButton label={`${t("loops.filter.all")} (${total})`} pressed={selected === "all"} onClick={() => onSelect("all")} />
      {presentStatuses.map((status) => (
        <FilterButton
          key={status}
          label={`${t(statusLabelKey(status))} (${counts[status]})`}
          pressed={selected === status}
          onClick={() => onSelect(status)}
        />
      ))}
    </div>
  );
}

/** The search box, export button and the "showing x of y" line above the table. */
function Toolbar({
  query,
  onChange,
  shown,
  total,
  onExport,
  t,
}: {
  query: OverviewQuery;
  onChange: (query: OverviewQuery) => void;
  shown: number;
  total: number;
  onExport: () => void;
  t: Translate;
}) {
  return (
    <div className="loops-toolbar">
      <label className="field loops-search">
        <span className="field-label">{t("loops.search")}</span>
        <input
          type="search"
          className="field-input"
          value={query.search}
          placeholder={t("loops.searchPlaceholder")}
          onChange={(event) => onChange({ ...query, search: event.target.value })}
        />
      </label>
      <p className="loops-count" aria-live="polite">
        {t("loops.shownOfTotal", { shown, total })}
      </p>
      <button type="button" className="filter-chip" onClick={onExport}>
        {t("loops.exportCsv")}
      </button>
    </div>
  );
}

/** A column header that sorts the table; `aria-sort` tells screen readers the current order. */
function SortableHeader({
  sortKey,
  label,
  query,
  onSort,
  t,
}: {
  sortKey: SortKey;
  label: string;
  query: OverviewQuery;
  onSort: (key: SortKey) => void;
  t: Translate;
}) {
  const order = ariaSort(query, sortKey);
  const arrow = order === "ascending" ? " ▲" : order === "descending" ? " ▼" : "";
  return (
    <th scope="col" aria-sort={order}>
      <button type="button" className="th-sort" title={t("loops.sortBy", { column: label })} onClick={() => onSort(sortKey)}>
        {label}
        <span aria-hidden="true">{arrow}</span>
      </button>
    </th>
  );
}

/** The table header; the sortable columns are buttons, the next-action and trend columns are not. */
function LoopsTableHeader({ query, onSort, t }: { query: OverviewQuery; onSort: (key: SortKey) => void; t: Translate }) {
  const header = (key: SortKey, labelKey: string) => (
    <SortableHeader sortKey={key} label={t(labelKey)} query={query} onSort={onSort} t={t} />
  );
  return (
    <thead>
      <tr>
        {header("priority", "loops.column.priority")}
        {header("status", "loops.column.status")}
        {header("loop", "loops.column.loop")}
        {header("health", "loops.column.health")}
        <th scope="col">{t("loops.column.finding")}</th>
        <th scope="col">{t("loops.column.action")}</th>
        {header("inUse", "loops.column.inUse")}
        <th scope="col">{t("loops.column.trend")}</th>
      </tr>
    </thead>
  );
}

/** Marks a loop whose analysis is incomplete; the hint names what has not been checked. */
function PartialMark({ loop, t }: { loop: LoopSummary; t: Translate }) {
  if (!isPartiallyAssessed(loop)) return null;
  const hint = t("loops.partialHint", { missing: withheldText(t, loop.not_assessed) });
  return (
    <span className="badge badge-partial" title={hint}>
      {t("loops.partial")}
    </span>
  );
}

/** One table row for a loop. "unused" loops are dimmed via the row class. */
function LoopRow({ loop, onOpen, t }: { loop: LoopSummary; onOpen: (loopName: string) => void; t: Translate }) {
  return (
    <tr className={loop.status === "unused" ? "row-unused" : undefined}>
      <td className="cell-rank">{loop.priority_rank}</td>
      <td>
        <StatusChip level={loop.status} label={t(statusLabelKey(loop.status))} />
      </td>
      <th scope="row" className="cell-loop">
        <button type="button" className="link-button" aria-label={t("loops.openLoop", { name: loop.name })} onClick={() => onOpen(loop.name)}>
          {loop.name}
        </button>
        <PartialMark loop={loop} t={t} />
      </th>
      <td className="cell-health" title={loop.health_percent === null ? t("health.notScoredHint") : undefined}>
        {loop.health_percent !== null && <progress max={100} value={loop.health_percent} aria-hidden="true" />}
        {formatHealth(loop)}
      </td>
      <td>{mainFindingText(t, loop)}</td>
      <td className="cell-action">{actionText(t, loop.next_action)}</td>
      <td>{`${loop.service_percent} %`}</td>
      <td>
        <Sparkline values={loop.sparkline} label={loop.name} />
      </td>
    </tr>
  );
}

/** Shown when the filters hide every loop; one click brings the list back. */
function NoMatch({ onClear, t }: { onClear: () => void; t: Translate }) {
  return (
    <div className="status">
      <p>{t("loops.noMatch")}</p>
      <button type="button" className="filter-chip" onClick={onClear}>
        {t("loops.clearFilters")}
      </button>
    </div>
  );
}

/**
 * Overview of every loop: attention line, status filters, search and the worklist table.
 * Shows a placeholder paragraph when there is no loop to display.
 */
export function LoopsOverview({
  loops,
  t,
  onOpen,
}: {
  loops: LoopSummary[];
  t: Translate;
  onOpen: (loopName: string) => void;
}) {
  const [query, setQuery] = useState<OverviewQuery>(DEFAULT_QUERY);
  const shownLoops = useMemo(() => applyQuery(loops, query), [loops, query]);

  if (loops.length === 0) {
    return <p className="status">{t("loops.none")}</p>;
  }

  return (
    <div className="loops-overview">
      <p className="loops-summary">{t("loops.attention", { count: loops.filter(needsAttention).length })}</p>
      <FilterBar
        counts={countByStatus(loops)}
        total={loops.length}
        selected={query.status}
        onSelect={(status) => setQuery({ ...query, status })}
        t={t}
      />
      <Toolbar
        query={query}
        onChange={setQuery}
        shown={shownLoops.length}
        total={loops.length}
        onExport={() => downloadCsv(loops, t)}
        t={t}
      />
      {shownLoops.length === 0 ? (
        <NoMatch onClear={() => setQuery(DEFAULT_QUERY)} t={t} />
      ) : (
        <div className="table-scroll">
          <table className="loops-table">
            <LoopsTableHeader query={query} onSort={(key) => setQuery(nextSort(query, key))} t={t} />
            <tbody>
              {shownLoops.map((loop) => (
                <LoopRow key={loop.name} loop={loop} onOpen={onOpen} t={t} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

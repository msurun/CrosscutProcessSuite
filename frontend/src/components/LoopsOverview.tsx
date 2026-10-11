// src/components/LoopsOverview.tsx
import { useState } from "react";
import type { LoopSummary, LoopStatus } from "../api";
import { StatusChip } from "./StatusChip";
import { Sparkline } from "./Sparkline";
import { compareLoops, mainFindingText, type Translate } from "../findings";

/** Every status the overview can display, in the order of the filter bar. */
const STATUS_ORDER: LoopStatus[] = ["problem", "warning", "ok", "unused"];

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

/**
 * Formats the health percentage for display.
 * Returns an en dash when the backend could not compute a health score.
 */
function formatHealth(loop: LoopSummary, t: Translate): string {
  if (loop.health_percent === null) {
    return "–";
  }
  return t("health.label", { percent: loop.health_percent });
}

/**
 * The line above the table, telling how many loops need attention.
 */
function AttentionLine({ count, t }: { count: number; t: Translate }): JSX.Element {
  return <p className="loops-summary">{t("loops.attention", { count })}</p>;
}

/** One filter button. `pressed` is the aria-pressed value, hence the name. */
function FilterButton({
  label,
  pressed,
  onClick,
}: {
  label: string;
  pressed: boolean;
  onClick: () => void;
}): JSX.Element {
  return (
    <button type="button" className="filter-chip" aria-pressed={pressed} onClick={onClick}>
      {label}
    </button>
  );
}

/**
 * The row of filter buttons: "All" plus one button per occurring status.
 * `selected` is the active filter; `onSelect` receives the newly chosen one.
 */
function FilterBar({
  counts,
  selected,
  onSelect,
  t,
}: {
  counts: Partial<Record<LoopStatus, number>>;
  selected: LoopStatus | "all";
  onSelect: (filter: LoopStatus | "all") => void;
  t: Translate;
}): JSX.Element {
  const presentStatuses = STATUS_ORDER.filter((status) => counts[status] !== undefined);
  return (
    <div className="loops-filters">
      <FilterButton
        label={t("loops.filter.all")}
        pressed={selected === "all"}
        onClick={() => onSelect("all")}
      />
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

/**
 * One table row for a loop. "unused" loops are dimmed via the row class.
 */
function LoopRow({
  loop,
  onOpen,
  t,
}: {
  loop: LoopSummary;
  onOpen: (loopName: string) => void;
  t: Translate;
}): JSX.Element {
  const rowClass = loop.status === "unused" ? "row-unused" : undefined;
  return (
    <tr className={rowClass}>
      <td>
        <StatusChip level={loop.status} label={t(statusLabelKey(loop.status))} />
      </td>
      <td>
        <button type="button" className="link-button" onClick={() => onOpen(loop.name)}>
          {loop.name}
        </button>
      </td>
      <td>
        <progress max={100} value={loop.health_percent ?? 0} aria-hidden="true" />
        {formatHealth(loop, t)}
      </td>
      <td>{mainFindingText(t, loop)}</td>
      <td>{`${loop.service_percent} %`}</td>
      <td>
        <Sparkline values={loop.sparkline} label={loop.name} />
      </td>
    </tr>
  );
}

/** The fixed table header, one cell per column. */
function LoopsTableHeader({ t }: { t: Translate }): JSX.Element {
  return (
    <thead>
      <tr>
        <th>{t("loops.column.status")}</th>
        <th>{t("loops.column.loop")}</th>
        <th>{t("loops.column.health")}</th>
        <th>{t("loops.column.finding")}</th>
        <th>{t("loops.column.inUse")}</th>
        <th>{t("loops.column.trend")}</th>
      </tr>
    </thead>
  );
}

/** The loops that match the active filter, sorted for display. */
function visibleLoops(loops: LoopSummary[], filter: LoopStatus | "all"): LoopSummary[] {
  const matching = filter === "all" ? loops : loops.filter((loop) => loop.status === filter);
  return [...matching].sort(compareLoops);
}

/**
 * Overview of every loop: a summary line, status filters and a sortable-looking table.
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
}): JSX.Element {
  const [filter, setFilter] = useState<LoopStatus | "all">("all");
  const attentionCount = loops.filter(needsAttention).length;

  if (loops.length === 0) {
    return <p className="status">{t("loops.none")}</p>;
  }

  const shownLoops = visibleLoops(loops, filter);
  return (
    <div className="loops-overview">
      <AttentionLine count={attentionCount} t={t} />
      <FilterBar counts={countByStatus(loops)} selected={filter} onSelect={setFilter} t={t} />
      <table className="loops-table">
        <LoopsTableHeader t={t} />
        <tbody>
          {shownLoops.map((loop) => (
            <LoopRow key={loop.name} loop={loop} onOpen={onOpen} t={t} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

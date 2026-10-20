// src/worklist.ts
//
// Pure logic behind the loop worklist: turning the backend's next action into a sentence, and
// filtering, searching and sorting the overview rows. Kept free of React so it is easy to test.

import type { LoopStatus, LoopSummary, NextAction } from "./api";
import type { Translate } from "./findings";

/** Columns the overview can be sorted by; "priority" is the backend's worklist order. */
export type SortKey = "priority" | "status" | "loop" | "health" | "inUse";
export type SortDirection = "asc" | "desc";

/** Everything the user can change on the overview toolbar. */
export interface OverviewQuery {
  status: LoopStatus | "all";
  search: string;
  sortKey: SortKey;
  sortDirection: SortDirection;
}

/** The overview as first opened: worklist order, nothing filtered. */
export const DEFAULT_QUERY: OverviewQuery = {
  status: "all",
  search: "",
  sortKey: "priority",
  sortDirection: "asc",
};

const STATUS_RANK: Record<LoopStatus, number> = {
  problem: 0,
  warning: 1,
  not_assessed: 2,
  ok: 3,
  unused: 4,
};

/** Sorts a missing health value after every real one, whatever the direction. */
const UNKNOWN_HEALTH = Number.POSITIVE_INFINITY;

/** Placeholder for a parameter the backend could not fill (for example an unknown percentage). */
const MISSING_PARAM = "–";

/** Names of withheld conclusions, as the backend lists them in `not_assessed`. */
const KNOWN_WITHHELD = ["saturation", "valve_kpis", "harris", "oscillation_amplitude"] as const;

/** True when per-loop knowledge is missing, so some conclusions were not drawn. */
export function isPartiallyAssessed(loop: LoopSummary): boolean {
  return loop.not_assessed.length > 0;
}

/** Turns one action parameter into text a translation template can embed. */
function paramText(value: NextAction["params"][string]): string | number {
  if (value === null || value === undefined) return MISSING_PARAM;
  if (typeof value === "string" || typeof value === "number") return value;
  return value.length === 0 ? MISSING_PARAM : value.join(", ");
}

/** Sentence for the loop's next action, for example "Find the shared source: cyc_water, mill_feed". */
export function actionText(t: Translate, action: NextAction): string {
  const params: Record<string, string | number> = {};
  for (const [name, value] of Object.entries(action.params)) {
    params[name] = name === "missing" ? missingText(t, value) : paramText(value);
  }
  return t(`action.${action.code}`, params);
}

/** Names the withheld conclusions in the user's language, e.g. "Harris index, saturation". */
function missingText(t: Translate, value: NextAction["params"][string]): string {
  const codes = Array.isArray(value) ? value : [];
  return codes.length === 0 ? MISSING_PARAM : withheldText(t, codes);
}

/** Human names of withheld conclusions; unknown codes are shown as the code itself. */
export function withheldText(t: Translate, codes: readonly string[]): string {
  const names = codes.map((code) =>
    (KNOWN_WITHHELD as readonly string[]).includes(code) ? t(`withheld.${code}`) : code,
  );
  return names.join(", ");
}

/** One-line search text of a loop: its name, tags and the words of its main finding codes. */
function searchText(loop: LoopSummary): string {
  const findings = loop.findings.map((finding) => finding.code).join(" ");
  return [loop.name, loop.pv, loop.classification, findings, loop.next_action.code].join(" ").toLowerCase();
}

/** Compares two loops by the chosen column in ascending order. */
function compareBy(key: SortKey, a: LoopSummary, b: LoopSummary): number {
  switch (key) {
    case "priority":
      return a.priority_rank - b.priority_rank;
    case "status":
      return STATUS_RANK[a.status] - STATUS_RANK[b.status];
    case "loop":
      return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" });
    case "health":
      return (a.health_percent ?? UNKNOWN_HEALTH) - (b.health_percent ?? UNKNOWN_HEALTH);
    case "inUse":
      return a.service_percent - b.service_percent;
  }
}

/** Ties on the chosen column fall back to the worklist order, so the list never jumps around. */
function compareLoops(query: OverviewQuery, a: LoopSummary, b: LoopSummary): number {
  if (query.sortKey === "health" && (a.health_percent === null) !== (b.health_percent === null)) {
    return a.health_percent === null ? 1 : -1; // unknown health is last in both directions
  }
  const sign = query.sortDirection === "asc" ? 1 : -1;
  const primary = compareBy(query.sortKey, a, b);
  return primary !== 0 ? sign * primary : a.priority_rank - b.priority_rank;
}

/** The rows to show: filtered by status and search text, then sorted. Does not change `loops`. */
export function applyQuery(loops: readonly LoopSummary[], query: OverviewQuery): LoopSummary[] {
  const needle = query.search.trim().toLowerCase();
  return loops
    .filter((loop) => query.status === "all" || loop.status === query.status)
    .filter((loop) => needle === "" || searchText(loop).includes(needle))
    .sort((a, b) => compareLoops(query, a, b));
}

/** Clicking a header: the same column flips the direction, a new column starts ascending. */
export function nextSort(query: OverviewQuery, key: SortKey): OverviewQuery {
  if (query.sortKey === key) {
    return { ...query, sortDirection: query.sortDirection === "asc" ? "desc" : "asc" };
  }
  return { ...query, sortKey: key, sortDirection: "asc" };
}

/** The `aria-sort` value of a column header. */
export function ariaSort(query: OverviewQuery, key: SortKey): "ascending" | "descending" | "none" {
  if (query.sortKey !== key) return "none";
  return query.sortDirection === "asc" ? "ascending" : "descending";
}

/** Quotes a CSV cell when it holds a separator, a quote or a line break. */
function csvCell(value: string | number | null): string {
  const text = value === null ? "" : String(value);
  return /[",;\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** The worklist as CSV (comma separated, header row first), for a meeting or a spreadsheet. */
export function worklistCsv(loops: readonly LoopSummary[], t: Translate): string {
  const header = ["priority", "loop", "status", "health_percent", "main_finding", "next_action", "not_assessed"];
  const rows = [...loops]
    .sort((a, b) => a.priority_rank - b.priority_rank)
    .map((loop) => [
      loop.priority_rank,
      loop.name,
      loop.status,
      loop.health_percent,
      loop.findings[0] ? t(`finding.${loop.findings[0].code}`, loop.findings[0].params) : "",
      actionText(t, loop.next_action),
      loop.not_assessed.join(" "),
    ]);
  return [header, ...rows].map((row) => row.map(csvCell).join(",")).join("\r\n");
}

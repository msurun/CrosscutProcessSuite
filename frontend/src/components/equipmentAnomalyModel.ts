// Equipment worklist helpers keep catalogue ordering and UTC window conversion explicit.
// The learning API accepts excluded closed intervals, not a selected window.
import type { DatasetSummary } from "../api";
import type { Equipment } from "./equipmentModel";

/** Resolve an area's name through the catalogue parents without following cycles. */
export function equipmentArea(entry: Equipment, entries: Equipment[]): string {
  const visited = new Set<string>();
  let current: Equipment | undefined = entry;
  while (current && !visited.has(current.id)) {
    if (current.level === "area") return current.name || current.id;
    visited.add(current.id);
    current = entries.find((candidate) => candidate.id === current?.parent);
  }
  return "";
}

/** Sort within each area by descending consequence, then by equipment identifier. */
export function orderedEquipment(entries: Equipment[]): Equipment[] {
  const priorities = ["critical", "high", "medium", "low"];
  const priority = (entry: Equipment) => {
    const index = priorities.indexOf(entry.criticality ?? "");
    return index < 0 ? priorities.length : index;
  };
  return entries.filter((entry) => (entry.level ?? "equipment") === "equipment")
    .sort((left, right) => equipmentArea(left, entries).localeCompare(equipmentArea(right, entries))
      || priority(left) - priority(right) || left.id.localeCompare(right.id));
}

/** Convert an inclusive UTC window to exclusions; reject ambiguous or out-of-record dates. */
export function learningExclusions(dataset: DatasetSummary, start: string, end: string): [string, string][] {
  const startTime = Date.parse(start), endTime = Date.parse(end);
  const first = Date.parse(dataset.time_range.start_utc), last = Date.parse(dataset.time_range.end_utc);
  const hasZone = (value: string) => /(?:Z|[+-]\d\d:\d\d)$/i.test(value);
  if (!hasZone(start) || !hasZone(end) || !Number.isFinite(startTime + endTime)
    || startTime >= endTime || startTime < first || endTime > last) {
    throw new RangeError("equipmentAnomaly.invalidWindow");
  }
  // Exclusions are closed. One millisecond outside the selected UTC bounds preserves boundary samples.
  const exclusions: [string, string][] = [];
  if (startTime > first) exclusions.push([dataset.time_range.start_utc, new Date(startTime - 1).toISOString()]);
  if (endTime < last) exclusions.push([new Date(endTime + 1).toISOString(), dataset.time_range.end_utc]);
  return exclusions;
}

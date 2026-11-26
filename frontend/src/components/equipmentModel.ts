// Pure helpers of the equipment hierarchy editor (#214): types, tree queries and immutable edits.
// Mirrors the rules of site_refs.py: a parent must be of a higher level, a loop has one primary owner.
export type Level = "site" | "area" | "unit" | "equipment";
export const LEVELS: Level[] = ["site", "area", "unit", "equipment"];
export const KINDS = ["temperature", "current", "power", "torque", "vibration", "speed", "ambient", "context"];
export const CRITICALITIES = ["low", "medium", "high", "critical"];

export interface ConditionSignal {
  tag: string;
  kind: string;
  confirmed: boolean;
}
export interface RunningState {
  tag: string;
  above: number;
  confirmed: boolean;
}
export interface Equipment {
  id: string;
  name?: string;
  level: Level;
  parent?: string;
  tags?: string[];
  criticality?: string;
  loops?: string[];
  loop_refs?: string[];
  signals?: ConditionSignal[];
  running?: RunningState;
}
/** The site document: only the parts the editor reads; the rest is kept untouched. */
export interface SiteDoc {
  equipment?: Equipment[];
  loops?: { id: string }[];
  tags?: { id: string }[];
  [key: string]: unknown;
}

export const levelIndex = (level: Level): number => LEVELS.indexOf(level);

export function childrenOf(list: Equipment[], id: string): Equipment[] {
  return list.filter((e) => e.parent === id);
}

/** Entries that may be the parent of `entry`: a strictly higher level. */
export function parentOptions(list: Equipment[], entry: Equipment): Equipment[] {
  return list.filter((e) => levelIndex(e.level) < levelIndex(entry.level));
}

/** Loop ids owned by an entry other than `exceptId`. */
export function ownedElsewhere(list: Equipment[], exceptId: string): Set<string> {
  return new Set(list.filter((e) => e.id !== exceptId).flatMap((e) => e.loops ?? []));
}

/** Number of proposals (signals and running state) still waiting for confirmation. */
export function unconfirmedCount(entry: Equipment): number {
  const open = (entry.signals ?? []).filter((s) => !s.confirmed).length;
  return open + (entry.running && !entry.running.confirmed ? 1 : 0);
}

export function confirmAll(list: Equipment[]): Equipment[] {
  return list.map((e) => ({
    ...e,
    ...(e.signals ? { signals: e.signals.map((s) => ({ ...s, confirmed: true })) } : {}),
    ...(e.running ? { running: { ...e.running, confirmed: true } } : {}),
  }));
}

export function updateEntry(list: Equipment[], id: string, patch: Partial<Equipment>): Equipment[] {
  return list.map((e) => (e.id === id ? { ...e, ...patch } : e));
}

/** Deleting is refused (null) while the entry still has children. */
export function removeEntry(list: Equipment[], id: string): Equipment[] | null {
  return childrenOf(list, id).length > 0 ? null : list.filter((e) => e.id !== id);
}

function freshId(list: Equipment[], base: string): string {
  let n = 1;
  while (list.some((e) => e.id === `${base}-${n}`)) n += 1;
  return `${base}-${n}`;
}

/** A new area (under the first site entry) or equipment (under `parentId`, else the first unit). */
export function addEntry(list: Equipment[], level: "area" | "equipment", parentId?: string): Equipment[] | null {
  const wanted: Level = level === "area" ? "site" : "unit";
  const chosen = list.find((e) => e.id === parentId && levelIndex(e.level) < levelIndex(level));
  const parent = chosen ?? list.find((e) => e.level === wanted);
  if (!parent) return null;
  return [...list, { id: freshId(list, level), name: "", level, parent: parent.id }];
}

export function toggle<T>(items: T[] | undefined, item: T): T[] {
  const list = items ?? [];
  return list.includes(item) ? list.filter((x) => x !== item) : [...list, item];
}

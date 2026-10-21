// src/tagGroups.ts
// Pure grouping of tags for the trends sidebar: by control loop, then by unit.
// Loops come from the analysis when available; otherwise the tag-name prefix before pv/sp/out/mode is used.

import type { LoopSummary, TagInfo } from "./api";

/** Tags of one unit inside a loop group. */
export interface UnitTags {
  unit: string;
  tags: TagInfo[];
}

/** All tags of one loop (or name prefix); an empty `loop` collects the tags that belong to none. */
export interface LoopTags {
  loop: string;
  units: UnitTags[];
}

/** Name suffixes that mark a loop signal in a tag id. */
const LOOP_SUFFIX = /^(.+)_(pv|sp|out|mode)$/i;

/** Maps each tag id of a loop (pv, sp, out, mode) to the loop name. */
function loopOfTag(loops: readonly LoopSummary[]): Map<string, string> {
  const owner = new Map<string, string>();
  for (const loop of loops) {
    for (const id of [loop.pv, loop.sp, loop.out, loop.mode]) owner.set(id, loop.name);
  }
  return owner;
}

/** The loop a tag belongs to: from the analysis, else its name prefix, else "". */
function loopName(tag: TagInfo, owner: ReadonlyMap<string, string>): string {
  return owner.get(tag.id) ?? LOOP_SUFFIX.exec(tag.id)?.[1] ?? "";
}

/** Adds `tag` to the unit bucket of `units`, creating the bucket in order of first appearance. */
function addToUnit(units: UnitTags[], tag: TagInfo): void {
  const unit = tag.unit ?? "";
  const bucket = units.find((one) => one.unit === unit);
  if (bucket) bucket.tags.push(tag);
  else units.push({ unit, tags: [tag] });
}

/**
 * Group tags by loop and, within each loop, by unit.
 *
 * Groups and units keep the order of first appearance; tags without a loop form a last group with loop "".
 */
export function groupTagsByLoop(tags: readonly TagInfo[], loops: readonly LoopSummary[]): LoopTags[] {
  const owner = loopOfTag(loops);
  const groups = new Map<string, UnitTags[]>();
  for (const tag of tags) {
    const name = loopName(tag, owner);
    const units = groups.get(name) ?? [];
    addToUnit(units, tag);
    groups.set(name, units);
  }
  const rest = groups.get("");
  groups.delete("");
  if (rest) groups.set("", rest);
  return [...groups].map(([loop, units]) => ({ loop, units }));
}

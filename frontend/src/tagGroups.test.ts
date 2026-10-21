// src/tagGroups.test.ts
// Tests of groupTagsByLoop: grouping by analysed loop, by name prefix, and by unit.
import { describe, expect, it } from "vitest";

import type { TagInfo } from "./api";
import { groupTagsByLoop } from "./tagGroups";
import { makeLoop } from "./testFixtures";

const tag = (id: string, unit?: string): TagInfo => ({ id, unit });

describe("groupTagsByLoop", () => {
  it("uses the loop names of the analysis", () => {
    const loops = [makeLoop({ name: "Flow 1", pv: "a", sp: "b", out: "c", mode: "d" })];
    const groups = groupTagsByLoop([tag("x"), tag("a", "m3/h"), tag("b", "m3/h"), tag("c", "%")], loops);
    expect(groups.map((g) => g.loop)).toEqual(["Flow 1", ""]);
    expect(groups[0].units.map((u) => [u.unit, u.tags.length])).toEqual([["m3/h", 2], ["%", 1]]);
  });

  it("falls back to the prefix before a pv/sp/out/mode suffix", () => {
    const groups = groupTagsByLoop([tag("FIC101_PV", "t"), tag("FIC101_SP", "t"), tag("TIC7_OUT", "%"), tag("pump")], []);
    expect(groups.map((g) => g.loop)).toEqual(["FIC101", "TIC7", ""]);
    expect(groups[0].units[0].tags.map((x) => x.id)).toEqual(["FIC101_PV", "FIC101_SP"]);
  });

  it("returns no groups for no tags", () => {
    expect(groupTagsByLoop([], [])).toEqual([]);
  });
});

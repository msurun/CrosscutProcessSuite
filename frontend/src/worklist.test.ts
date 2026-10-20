// Tests for the loop worklist logic: filtering, sorting, the next-action sentences and the CSV
// export. Every fixture is built by `makeLoop`, so a test only states the fields it cares about.

import { describe, expect, it } from "vitest";

import { makeLoop } from "./testFixtures";
import type { Translate } from "./findings";
import {
  actionText,
  applyQuery,
  ariaSort,
  DEFAULT_QUERY,
  isPartiallyAssessed,
  nextSort,
  withheldText,
  worklistCsv,
  type OverviewQuery,
} from "./worklist";

/** Echoes the key and its params, so a test can read back what the translator received. */
const t: Translate = (key, params) => key + JSON.stringify(params ?? {});

/** A query with only the given fields changed from the default. */
function makeQuery(overrides: Partial<OverviewQuery> = {}): OverviewQuery {
  return { ...DEFAULT_QUERY, ...overrides };
}

describe("applyQuery", () => {
  it("keeps only the loops with the chosen status when a status is picked", () => {
    const loops = [
      makeLoop({ name: "A", status: "problem" }),
      makeLoop({ name: "B", status: "ok" }),
      makeLoop({ name: "C", status: "problem" }),
    ];

    const rows = applyQuery(loops, makeQuery({ status: "problem" }));

    expect(rows.map((loop) => loop.name)).toEqual(["A", "C"]);
  });

  it("finds a loop by text in its name", () => {
    const loops = [makeLoop({ name: "TIC-101" }), makeLoop({ name: "FIC-202", priority_rank: 2 })];

    const rows = applyQuery(loops, makeQuery({ search: "fic" }));

    expect(rows.map((loop) => loop.name)).toEqual(["FIC-202"]);
  });

  it("finds a loop by a tag name", () => {
    const loops = [makeLoop({ pv: "TIC101.PV" }), makeLoop({ pv: "FIC202.PV", priority_rank: 2 })];

    const rows = applyQuery(loops, makeQuery({ search: "fic202" }));

    expect(rows.map((loop) => loop.pv)).toEqual(["FIC202.PV"]);
  });

  it("finds a loop by the code of one of its findings", () => {
    const loops = [
      makeLoop({ name: "A", findings: [{ code: "saturated", params: {} }] }),
      makeLoop({ name: "B", priority_rank: 2 }),
    ];

    const rows = applyQuery(loops, makeQuery({ search: "saturated" }));

    expect(rows.map((loop) => loop.name)).toEqual(["A"]);
  });

  it("sorts by status with problems first when ascending", () => {
    const loops = [
      makeLoop({ name: "ok", status: "ok", priority_rank: 1 }),
      makeLoop({ name: "problem", status: "problem", priority_rank: 2 }),
      makeLoop({ name: "warning", status: "warning", priority_rank: 3 }),
    ];

    const rows = applyQuery(loops, makeQuery({ sortKey: "status", sortDirection: "asc" }));

    expect(rows.map((loop) => loop.name)).toEqual(["problem", "warning", "ok"]);
  });

  it("reverses the order when the sort direction is descending", () => {
    const loops = [
      makeLoop({ name: "A", priority_rank: 1 }),
      makeLoop({ name: "B", priority_rank: 2 }),
      makeLoop({ name: "C", priority_rank: 3 }),
    ];

    const rows = applyQuery(loops, makeQuery({ sortKey: "priority", sortDirection: "desc" }));

    expect(rows.map((loop) => loop.name)).toEqual(["C", "B", "A"]);
  });

  it("sorts by loop name in natural order so TIC-2 comes before TIC-10", () => {
    const loops = [
      makeLoop({ name: "TIC-10", priority_rank: 1 }),
      makeLoop({ name: "TIC-2", priority_rank: 2 }),
    ];

    const rows = applyQuery(loops, makeQuery({ sortKey: "loop" }));

    expect(rows.map((loop) => loop.name)).toEqual(["TIC-2", "TIC-10"]);
  });

  it("sorts by health ascending, putting an unknown health last", () => {
    const loops = [
      makeLoop({ name: "unknown", health_percent: null, priority_rank: 1 }),
      makeLoop({ name: "low", health_percent: 20, priority_rank: 2 }),
      makeLoop({ name: "high", health_percent: 95, priority_rank: 3 }),
    ];

    const rows = applyQuery(loops, makeQuery({ sortKey: "health", sortDirection: "asc" }));
    expect(rows.map((loop) => loop.name)).toEqual(["low", "high", "unknown"]);
  });

  it("puts an unknown health last even when the direction is descending", () => {
    const loops = [
      makeLoop({ name: "unknown", health_percent: null, priority_rank: 1 }),
      makeLoop({ name: "low", health_percent: 20, priority_rank: 2 }),
      makeLoop({ name: "high", health_percent: 95, priority_rank: 3 }),
    ];

    const rows = applyQuery(loops, makeQuery({ sortKey: "health", sortDirection: "desc" }));

    expect(rows.map((loop) => loop.name)).toEqual(["high", "low", "unknown"]);
  });

  it("sorts by in-use percentage", () => {
    const loops = [
      makeLoop({ name: "half", service_percent: 50, priority_rank: 1 }),
      makeLoop({ name: "full", service_percent: 100, priority_rank: 2 }),
      makeLoop({ name: "idle", service_percent: 5, priority_rank: 3 }),
    ];

    const rows = applyQuery(loops, makeQuery({ sortKey: "inUse", sortDirection: "asc" }));

    expect(rows.map((loop) => loop.name)).toEqual(["idle", "half", "full"]);
  });

  it("breaks ties on the sort column by priority rank", () => {
    const loops = [
      makeLoop({ name: "later", status: "ok", priority_rank: 5 }),
      makeLoop({ name: "first", status: "ok", priority_rank: 2 }),
      makeLoop({ name: "middle", status: "ok", priority_rank: 3 }),
    ];

    const rows = applyQuery(loops, makeQuery({ sortKey: "status", sortDirection: "desc" }));

    expect(rows.map((loop) => loop.name)).toEqual(["first", "middle", "later"]);
  });

  it("does not reorder the input array it was given", () => {
    const loops = [
      makeLoop({ name: "B", priority_rank: 2 }),
      makeLoop({ name: "A", priority_rank: 1 }),
    ];

    applyQuery(loops, makeQuery({ sortKey: "priority", sortDirection: "asc" }));

    expect(loops.map((loop) => loop.name)).toEqual(["B", "A"]);
  });
});

describe("nextSort", () => {
  it("flips the direction when the same column is clicked again", () => {
    const query = makeQuery({ sortKey: "health", sortDirection: "asc" });

    expect(nextSort(query, "health").sortDirection).toBe("desc");
  });

  it("starts a new column in ascending order", () => {
    const query = makeQuery({ sortKey: "health", sortDirection: "desc" });

    expect(nextSort(query, "loop")).toMatchObject({ sortKey: "loop", sortDirection: "asc" });
  });
});

describe("ariaSort", () => {
  it("reports ascending when the column is sorted ascending", () => {
    expect(ariaSort(makeQuery({ sortKey: "loop", sortDirection: "asc" }), "loop")).toBe("ascending");
  });

  it("reports none for a column that is not the sort column", () => {
    expect(ariaSort(makeQuery({ sortKey: "loop" }), "health")).toBe("none");
  });
});

describe("isPartiallyAssessed", () => {
  it("is true when a conclusion was withheld", () => {
    expect(isPartiallyAssessed(makeLoop({ not_assessed: ["harris"] }))).toBe(true);
  });

  it("is false when every conclusion could be drawn", () => {
    expect(isPartiallyAssessed(makeLoop({ not_assessed: [] }))).toBe(false);
  });
});

describe("actionText", () => {
  it("looks up the action key and passes the parameters through", () => {
    const action = { code: "check_output_limit", params: { percent: 31 } } as const;

    expect(actionText(t, action)).toBe('action.check_output_limit{"percent":31}');
  });

  it("joins a list parameter with a comma", () => {
    const action = { code: "find_common_source", params: { loops: ["cyc_water", "mill_feed"] } } as const;

    expect(actionText(t, action)).toBe('action.find_common_source{"loops":"cyc_water, mill_feed"}');
  });

  it("shows a dash for a parameter the backend could not fill", () => {
    const action = { code: "check_output_limit", params: { percent: null } } as const;

    expect(actionText(t, action)).toBe('action.check_output_limit{"percent":"–"}');
  });

  it("translates the withheld codes of a missing parameter", () => {
    const action = { code: "configure_knowledge", params: { missing: ["harris", "saturation"] } } as const;

    expect(actionText(t, action)).toBe('action.configure_knowledge{"missing":"withheld.harris{}, withheld.saturation{}"}');
  });
});

describe("withheldText", () => {
  it("shows the translated name of a known conclusion", () => {
    expect(withheldText(t, ["oscillation_amplitude"])).toBe("withheld.oscillation_amplitude{}");
  });

  it("shows the code itself for a conclusion it does not know", () => {
    expect(withheldText(t, ["brand_new_check"])).toBe("brand_new_check");
  });
});

describe("worklistCsv", () => {
  it("starts with the header row", () => {
    const csv = worklistCsv([makeLoop()], t);

    expect(csv.split("\r\n")[0]).toBe(
      "priority,loop,status,health_percent,main_finding,next_action,not_assessed",
    );
  });

  it("lists the loops in priority order whatever order they came in", () => {
    const loops = [makeLoop({ name: "B", priority_rank: 2 }), makeLoop({ name: "A", priority_rank: 1 })];

    const csv = worklistCsv(loops, t);

    expect(csv.split("\r\n").slice(1).map((line) => line.split(",")[1])).toEqual(["A", "B"]);
  });

  it("quotes a cell holding a comma and doubles the quotes inside it", () => {
    const loop = makeLoop({ name: 'Flow, "main"' });

    expect(worklistCsv([loop], t)).toContain('1,"Flow, ""main""",ok');
  });

  it("leaves the health cell empty when the health is unknown", () => {
    const loop = makeLoop({ health_percent: null });

    expect(worklistCsv([loop], t)).toContain(",ok,,");
  });

  it("separates the lines with CRLF", () => {
    const csv = worklistCsv([makeLoop()], t);

    expect(csv.endsWith("\r\n") || csv.includes("\r\n")).toBe(true);
  });
});

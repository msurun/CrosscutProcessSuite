// Tests of the pure site edits behind accepting mode and equipment proposals (#145).
import { describe, expect, it } from "vitest";

import type { EquipmentProposal, ModeProposal } from "./modeProposalApi";
import { acceptEquipment, acceptMode, formatWindow, parseClauses } from "./modeProposalModel";

const evidence = { kind: "bimodal_gap", share: 0.3, thresholds: {}, windows: [], events: 1, detail: "" };
const group: EquipmentProposal = {
  id: "PMP7",
  confidence: "high",
  evidence,
  entry: { id: "PMP7", name: "PMP7", level: "equipment", tags: ["PMP7_RUN", "PMP7_CURR"] },
};
const stopped: ModeProposal = {
  id: "PMP7_stopped",
  confidence: "high",
  evidence,
  scope_new: true,
  entry: {
    id: "PMP7_stopped",
    name: "PMP7 stopped",
    scope: "PMP7",
    condition: { match: "all", clauses: [{ tag: "PMP7_CURR", op: "<=", value: 3 }] },
  },
};

describe("acceptEquipment", () => {
  it("adds the entry under a new site root and registers its tags", () => {
    const site = acceptEquipment({}, group);
    expect(site.equipment).toEqual([
      { id: "site", level: "site" },
      { ...group.entry, parent: "site" },
    ]);
    expect(site.tags).toEqual([{ id: "PMP7_RUN" }, { id: "PMP7_CURR" }]);
  });

  it("uses the existing site entry and never duplicates an id", () => {
    const start = { equipment: [{ id: "plant", level: "site" as const }], tags: [{ id: "PMP7_RUN" }] };
    const once = acceptEquipment(start, group);
    expect(once.equipment?.[1].parent).toBe("plant");
    expect(once.tags).toHaveLength(2);
    expect(acceptEquipment(once, group)).toBe(once);
  });
});

describe("acceptMode", () => {
  it("stores the edited clauses and adds the proposed equipment with it", () => {
    const edited = [{ tag: "PMP7_CURR", op: "<=" as const, value: 4.5 }];
    const site = acceptMode({}, stopped, edited, group);
    expect(site.modes).toEqual([{ ...stopped.entry, condition: { match: "all", clauses: edited } }]);
    expect(site.equipment?.some((e) => e.id === "PMP7")).toBe(true);
  });

  it("replaces a mode with the same id", () => {
    const first = acceptMode({}, stopped, stopped.entry.condition.clauses, group);
    const again = acceptMode(first, stopped, [{ tag: "PMP7_CURR", op: "<=", value: 9 }], group);
    expect(again.modes).toHaveLength(1);
  });
});

describe("parseClauses", () => {
  const clauses = stopped.entry.condition.clauses;
  it("turns typed text into numbers", () => {
    expect(parseClauses(clauses, ["12.5"])?.[0].value).toBe(12.5);
  });
  it("refuses text and blanks", () => {
    expect(parseClauses(clauses, ["abc"])).toBeNull();
    expect(parseClauses(clauses, [" "])).toBeNull();
  });
});

describe("formatWindow", () => {
  it("writes seconds since start as clock times", () => {
    expect(formatWindow([3000, 3725])).toBe("0:50:00 - 1:02:05");
  });
});

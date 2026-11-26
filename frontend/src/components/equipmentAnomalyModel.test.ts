// Behaviour tests for catalogue grouping and inclusive learning windows.
// Synthetic UTC records make the exclusion boundary contract reproducible.
import { describe, expect, it } from "vitest";
import type { DatasetSummary } from "../api";
import type { Equipment } from "./equipmentModel";
import { equipmentArea, learningExclusions, orderedEquipment } from "./equipmentAnomalyModel";

const DATASET: DatasetSummary = {
  id: "pump-data", source: {}, n_tags: 2, n_samples: 300,
  time_range: { start_utc: "2026-01-01T00:00:00Z", end_utc: "2026-01-01T01:00:00Z" },
};
const AREA: Equipment = { id: "area", name: "Grinding", level: "area" };
const PUMP: Equipment = { id: "pump", parent: "unit", level: "equipment", criticality: "high" };

describe("equipment areas", () => {
  it("finds an area through an intermediate unit", () => {
    expect(equipmentArea(PUMP, [AREA, { id: "unit", parent: "area", level: "unit" }, PUMP]))
      .toBe("Grinding");
  });
  it("ends safely when malformed parents form a cycle", () => {
    expect(equipmentArea(PUMP, [PUMP, { id: "unit", parent: "pump", level: "unit" }])).toBe("");
  });
  it("keeps unassigned equipment visible", () => {
    expect(equipmentArea({ ...PUMP, parent: undefined }, [AREA])).toBe("");
  });
});

describe("equipment ordering", () => {
  it("groups by area then ranks critical equipment before low priority equipment", () => {
    const low: Equipment = { id: "low", level: "equipment", parent: "area", criticality: "low" };
    const critical: Equipment = { id: "critical", level: "equipment", parent: "area", criticality: "critical" };
    const otherArea: Equipment = { id: "other", name: "Zinc", level: "area" };
    const other: Equipment = { id: "other-pump", level: "equipment", parent: "other", criticality: "critical" };
    const entries = [other, low, AREA, critical, otherArea];
    expect(orderedEquipment(entries).map((entry) => entry.id)).toEqual(["critical", "low", "other-pump"]);
    expect(entries[0]).toBe(other);
  });
});

describe("learning exclusions", () => {
  it("sends no exclusions for the whole record", () => {
    expect(learningExclusions(DATASET, DATASET.time_range.start_utc, DATASET.time_range.end_utc)).toEqual([]);
  });
  it("preserves both selected boundaries outside closed exclusions", () => {
    expect(learningExclusions(DATASET, "2026-01-01T00:10:00Z", "2026-01-01T00:20:00Z")).toEqual([
      ["2026-01-01T00:00:00Z", "2026-01-01T00:09:59.999Z"],
      ["2026-01-01T00:20:00.001Z", "2026-01-01T01:00:00Z"],
    ]);
  });
  it("accepts explicit offsets as timezone evidence", () => {
    expect(learningExclusions(DATASET, "2025-12-31T21:00:00-03:00", "2025-12-31T22:00:00-03:00")).toEqual([]);
  });
  it("rejects timezone-free timestamps", () => {
    expect(() => learningExclusions(DATASET, "2026-01-01T00:00:00", DATASET.time_range.end_utc)).toThrow(RangeError);
  });
  it("rejects windows outside the record", () => {
    expect(() => learningExclusions(DATASET, "2025-12-31T23:59:00Z", DATASET.time_range.end_utc)).toThrow(RangeError);
  });
  it("rejects reversed windows", () => {
    expect(() => learningExclusions(DATASET, DATASET.time_range.end_utc, DATASET.time_range.start_utc)).toThrow(RangeError);
  });
  it("rejects invalid dates", () => {
    expect(() => learningExclusions(DATASET, "invalidZ", DATASET.time_range.end_utc)).toThrow(RangeError);
  });
});


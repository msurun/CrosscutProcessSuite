// Verify start-page selection independently of network requests and rendering.
// Synthetic rows distinguish open findings from closed and shelved evidence.
import { describe, expect, it } from "vitest";
import type { LiveLoop } from "./liveLoopsApi";
import type { EquipmentAnomaly } from "./equipmentAnomalyApi";
import { activeAnomalies, activeEquipmentAlarms, topLoopFindings } from "./overviewModel";

const LOOP: LiveLoop = { id: "flow", name: "Flow", type: null, job: "kpi", job_status: "ok",
  last_run_utc: null, fresh: true, kpi: {}, findings: [{ code: "stiction", since_utc: null }] };
const EQUIPMENT: EquipmentAnomaly = { equipment_id: "pump", model_status: "learned",
  live_state: { status: "anomaly" }, open_event: null, events: [], shelved_until_utc: null };

describe("overview summaries", () => {
  it("has no top findings for an empty worklist", () => {
    expect(topLoopFindings([])).toEqual([]);
  });
  it("leaves healthy loops out of the findings shortcut", () => {
    expect(topLoopFindings([{ ...LOOP, findings: [] }, LOOP])).toEqual([LOOP]);
  });
  it("limits the shortcut without mutating server worklist order", () => {
    const rows = Array.from({ length: 7 }, (_, index) => ({ ...LOOP, id: String(index) }));
    expect(topLoopFindings(rows).map((row) => row.id)).toEqual(["0", "1", "2", "3", "4"]);
    expect(rows).toHaveLength(7);
  });
  it("ignores closed historical events in current findings", () => {
    expect(activeAnomalies([{ ...EQUIPMENT, live_state: { status: "ok" } }])).toEqual([]);
  });
  it("shows a currently anomalous equipment item", () => {
    expect(activeAnomalies([EQUIPMENT])).toEqual([EQUIPMENT]);
  });
  it("keeps shelved findings out of alarm notifications", () => {
    const shelved = { ...EQUIPMENT, live_state: { ...EQUIPMENT.live_state, shelved: true } };
    expect(activeEquipmentAlarms([shelved])).toEqual([]);
    expect(activeAnomalies([shelved])).toEqual([shelved]);
  });
  it("suppresses an alarm until the shelving expiry", () => {
    const shelved = { ...EQUIPMENT, shelved_until_utc: "2026-11-26T12:00:00Z" };
    expect(activeEquipmentAlarms([shelved], Date.parse("2026-11-26T11:00:00Z"))).toEqual([]);
  });
  it("shows an alarm after its shelving expiry", () => {
    const expired = { ...EQUIPMENT, shelved_until_utc: "2026-11-26T10:00:00Z" };
    expect(activeEquipmentAlarms([expired], Date.parse("2026-11-26T11:00:00Z"))).toEqual([expired]);
  });
});

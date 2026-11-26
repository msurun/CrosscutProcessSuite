// Unit tests of the status bar model (#174): item building per source state, kill detection, alarm counting.
import { describe, expect, it } from "vitest";

import type { EquipmentAnomaly } from "./equipmentAnomalyApi";
import type { LiveLoop } from "./liveLoopsApi";
import { buildItems, countAlarms, LOADING_DATA, type StatusBarData } from "./statusBarModel";

const loop = (codes: string[]): LiveLoop => ({
  id: "L", name: "L", type: null, job: null, job_status: null, last_run_utc: null, fresh: true, kpi: null,
  findings: codes.map((code) => ({ code, since_utc: null })),
});
const equipment = (status: "anomaly" | "ok", shelved = false): EquipmentAnomaly => ({
  equipment_id: "E", model_status: "learned", live_state: { status, shelved }, open_event: null, events: [], shelved_until_utc: null,
});

const READY: StatusBarData = {
  gateway: { state: "ready", value: { mode: "confirm", targets: { a: "enabled" }, pending: 3 } },
  runtime: { state: "ready", value: { service: { running: true, updated_at_utc: null }, jobs: [] } },
  loops: { state: "ready", value: [loop(["x"]), loop([])] },
  equipment: { state: "ready", value: [equipment("anomaly"), equipment("anomaly", true), equipment("ok")] },
};

describe("buildItems", () => {
  it("is loading for every item at the start", () => {
    expect(buildItems(LOADING_DATA).every((i) => i.availability === "loading" && i.valueKey === null)).toBe(true);
  });

  it("fills all five items from ready data", () => {
    const items = Object.fromEntries(buildItems(READY).map((i) => [i.id, i]));
    expect(items.mode.valueKey).toBe("gateway.mode.confirm");
    expect(items.kill.level).toBe("ok");
    expect(items.queue.params).toEqual({ count: 3 });
    expect(items.queue.level).toBe("warning");
    expect(items.runtime.valueKey).toBe("statusBar.runtime.running");
    expect(items.alarms.params).toEqual({ count: 2 });
  });

  it("shows a killed target as a problem", () => {
    const gateway = { state: "ready" as const, value: { mode: "off", targets: { a: "killed" }, pending: 0 } };
    const kill = buildItems({ ...READY, gateway }).find((i) => i.id === "kill");
    expect(kill).toMatchObject({ level: "problem", valueKey: "statusBar.kill.active" });
  });

  it("degrades per source", () => {
    const items = buildItems({ ...READY, gateway: { state: "unavailable" }, equipment: { state: "unavailable" } });
    const by = Object.fromEntries(items.map((i) => [i.id, i.availability]));
    expect(by).toEqual({ mode: "unavailable", kill: "unavailable", queue: "unavailable", runtime: "ready", alarms: "unavailable" });
  });
});

describe("countAlarms", () => {
  it("counts loops with findings and open unshelved anomalies", () => {
    expect(countAlarms([loop(["a", "b"])], [equipment("anomaly")])).toBe(2);
    expect(countAlarms([], [])).toBe(0);
  });
});

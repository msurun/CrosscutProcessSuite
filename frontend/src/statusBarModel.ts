// Pure model of the global status bar (#174): turns the answers of the existing gateway, runtime,
// live-loop and equipment-anomaly APIs into display items. No React, no network: easy to test.
import type { RuntimeStatus } from "./api";
import type { EquipmentAnomaly } from "./equipmentAnomalyApi";
import type { GatewayStatus } from "./gatewayApi";
import type { LiveLoop } from "./liveLoopsApi";

/** One source of the bar: still loading, failed, or loaded. A failure only hides that source. */
export type Slot<T> = { state: "loading" } | { state: "unavailable" } | { state: "ready"; value: T };

/** The raw answers of the four sources. */
export interface StatusBarData {
  gateway: Slot<GatewayStatus>;
  runtime: Slot<RuntimeStatus>;
  loops: Slot<LiveLoop[]>;
  equipment: Slot<EquipmentAnomaly[]>;
}

/** Severity of an item; mirrors the StatusChip levels. */
export type ItemLevel = "ok" | "warning" | "problem" | "unused";

/** What one item shows: `valueKey` is a locale key (filled with `params`) or null while loading / unavailable. */
export interface StatusItem {
  id: "mode" | "kill" | "queue" | "runtime" | "alarms";
  availability: "loading" | "unavailable" | "ready";
  level: ItemLevel;
  valueKey: string | null;
  params?: Record<string, number | string>;
}

/** Initial data: everything loading. */
export const LOADING_DATA: StatusBarData = {
  gateway: { state: "loading" },
  runtime: { state: "loading" },
  loops: { state: "loading" },
  equipment: { state: "loading" },
};

const MODE_KEYS: Record<string, string> = {
  off: "gateway.mode.off",
  advisory: "gateway.mode.advisory",
  dry_run: "gateway.mode.dry_run",
  confirm: "gateway.mode.confirm",
  supervised: "gateway.mode.supervised",
};

/** Item without a value while its source loads or failed. */
function withoutValue(id: StatusItem["id"], state: "loading" | "unavailable"): StatusItem {
  return { id, availability: state, level: "unused", valueKey: null };
}

/** True when at least one write target was emergency-killed. */
export function isKilled(status: GatewayStatus): boolean {
  return Object.values(status.targets).includes("killed");
}

/** Number of loops with findings plus equipment items with an open, not shelved anomaly. */
export function countAlarms(loops: LiveLoop[], equipment: EquipmentAnomaly[]): number {
  const loopAlarms = loops.filter((loop) => loop.findings.length > 0).length;
  const equipmentAlarms = equipment.filter((one) => one.live_state.status === "anomaly" && !one.live_state.shelved).length;
  return loopAlarms + equipmentAlarms;
}

/** Builds the three gateway-backed items, or three value-less ones when the gateway is not ready. */
function gatewayItems(slot: StatusBarData["gateway"]): StatusItem[] {
  if (slot.state !== "ready") return (["mode", "kill", "queue"] as const).map((id) => withoutValue(id, slot.state));
  const status = slot.value;
  const killed = isKilled(status);
  return [
    {
      id: "mode", availability: "ready", level: status.mode === "off" ? "unused" : "ok",
      valueKey: MODE_KEYS[status.mode] ?? "statusBar.mode.unknown",
    },
    {
      id: "kill", availability: "ready", level: killed ? "problem" : "ok",
      valueKey: killed ? "statusBar.kill.active" : "statusBar.kill.clear",
    },
    {
      id: "queue", availability: "ready", level: status.pending > 0 ? "warning" : "ok",
      valueKey: "statusBar.queue.count", params: { count: status.pending },
    },
  ];
}

function runtimeItem(slot: StatusBarData["runtime"]): StatusItem {
  if (slot.state !== "ready") return withoutValue("runtime", slot.state);
  const running = slot.value.service.running;
  return {
    id: "runtime", availability: "ready", level: running ? "ok" : "warning",
    valueKey: running ? "statusBar.runtime.running" : "statusBar.runtime.stopped",
  };
}

/** Alarms need both sources; one failed source makes the count unavailable (no false zero). */
function alarmsItem({ loops, equipment }: StatusBarData): StatusItem {
  if (loops.state === "unavailable" || equipment.state === "unavailable") return withoutValue("alarms", "unavailable");
  if (loops.state !== "ready" || equipment.state !== "ready") return withoutValue("alarms", "loading");
  const count = countAlarms(loops.value, equipment.value);
  return {
    id: "alarms", availability: "ready", level: count > 0 ? "problem" : "ok",
    valueKey: "statusBar.alarms.count", params: { count },
  };
}

/** The five items of the bar, in display order. */
export function buildItems(data: StatusBarData): StatusItem[] {
  return [...gatewayItems(data.gateway), runtimeItem(data.runtime), alarmsItem(data)];
}

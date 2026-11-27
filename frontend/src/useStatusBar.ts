// Polls the existing read-only APIs for the global status bar (#174). Each source fails alone:
// a failed call turns only its slot "unavailable"; the next poll tries again.
import { useEffect, useState } from "react";

import { fetchRuntimeStatus, type RuntimeStatus } from "./api";
import { fetchEquipmentAnomalies, type EquipmentAnomaly } from "./equipmentAnomalyApi";
import { fetchGatewayStatus, type GatewayStatus } from "./gatewayApi";
import { fetchLiveLoops, type LiveLoop } from "./liveLoopsApi";
import { LOADING_DATA, type Slot, type StatusBarData } from "./statusBarModel";

/** Poll interval in milliseconds; the data is a summary, so a modest rate is enough. */
export const STATUS_POLL_MS = 15000;

/** Runs `load` and wraps the outcome as a slot; never throws. A body that fails `valid` counts as unavailable. */
async function toSlot<T>(load: () => Promise<T>, valid: (value: T) => boolean): Promise<Slot<T>> {
  try {
    const value = await load();
    return valid(value) ? { state: "ready", value } : { state: "unavailable" };
  } catch {
    return { state: "unavailable" };
  }
}

/** Shape checks: a proxy or mock may answer with another JSON body, which must not crash the bar. */
const isObject = (value: unknown): boolean => typeof value === "object" && value !== null && !Array.isArray(value);
const validGateway = (v: GatewayStatus): boolean => isObject(v) && isObject(v.targets) && typeof v.pending === "number";
const validRuntime = (v: RuntimeStatus): boolean => isObject(v) && isObject(v.service);
const validLoops = (v: LiveLoop[]): boolean => Array.isArray(v) && v.every((l) => Array.isArray(l?.findings));
const validEquipment = (v: EquipmentAnomaly[]): boolean => Array.isArray(v) && v.every((e) => isObject(e?.live_state));

/** Fetches all four sources in parallel. */
export async function loadStatusBarData(): Promise<StatusBarData> {
  const [gateway, runtime, loops, equipment] = await Promise.all([
    toSlot(fetchGatewayStatus, validGateway),
    toSlot(fetchRuntimeStatus, validRuntime),
    toSlot(fetchLiveLoops, validLoops),
    toSlot(fetchEquipmentAnomalies, validEquipment),
  ]);
  return { gateway, runtime, loops, equipment };
}

/** The current status-bar data, refreshed every `intervalMs` while mounted. */
export function useStatusBarData(intervalMs: number = STATUS_POLL_MS): StatusBarData {
  const [data, setData] = useState<StatusBarData>(LOADING_DATA);
  useEffect(() => {
    let cancelled = false;
    const refresh = () => {
      void loadStatusBarData().then((next) => {
        if (!cancelled) setData(next);
      });
    };
    refresh();
    const timer = window.setInterval(refresh, intervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [intervalMs]);
  return data;
}

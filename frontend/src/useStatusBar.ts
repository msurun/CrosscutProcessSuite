// Polls the existing read-only APIs for the global status bar (#174). Each source fails alone:
// a failed call turns only its slot "unavailable"; the next poll tries again.
import { useEffect, useState } from "react";

import { fetchRuntimeStatus } from "./api";
import { fetchEquipmentAnomalies } from "./equipmentAnomalyApi";
import { fetchGatewayStatus } from "./gatewayApi";
import { fetchLiveLoops } from "./liveLoopsApi";
import { LOADING_DATA, type Slot, type StatusBarData } from "./statusBarModel";

/** Poll interval in milliseconds; the data is a summary, so a modest rate is enough. */
export const STATUS_POLL_MS = 15000;

/** Runs `load` and wraps the outcome as a slot; never throws. */
async function toSlot<T>(load: () => Promise<T>): Promise<Slot<T>> {
  try {
    return { state: "ready", value: await load() };
  } catch {
    return { state: "unavailable" };
  }
}

/** Fetches all four sources in parallel. */
export async function loadStatusBarData(): Promise<StatusBarData> {
  const [gateway, runtime, loops, equipment] = await Promise.all([
    toSlot(fetchGatewayStatus),
    toSlot(fetchRuntimeStatus),
    toSlot(fetchLiveLoops),
    toSlot(fetchEquipmentAnomalies),
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

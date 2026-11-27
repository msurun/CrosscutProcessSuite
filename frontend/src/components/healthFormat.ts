// frontend/src/components/healthFormat.ts
// Text of the Health page (#170): item label, reason and detail lines in the user's language.
// Pure functions of an item and the translator, so the unit test checks them without a DOM.

import type { Translate } from "../findings";
import type { HealthItem, HealthStatus } from "../healthApi";
import type { StatusLevel } from "./StatusChip";

const GIB = 2 ** 30;

/** The chip level of an item status. */
export function levelOf(status: HealthStatus): StatusLevel {
  return status === "error" ? "problem" : status;
}

/** Short title of an item: fixed items by id, jobs and controllers with their name. */
export function itemLabel(item: HealthItem, t: Translate): string {
  if (item.id.startsWith("job:")) return t("health.label.job", { id: item.id.slice(4) });
  if (item.id.startsWith("liveness:controller:")) {
    return t("health.label.controller", { id: item.id.slice("liveness:controller:".length) });
  }
  const key = `health.label.${item.id.replace(":", "_")}`;
  const text = t(key);
  return text === key ? item.id : text;
}

/** The reason in the user's language; the server's English text when the code is unknown. */
export function itemReason(item: HealthItem, t: Translate): string {
  const d = item.details;
  const key = `health.reason.${item.code}`;
  const text = t(key, {
    mode: d.mode ?? "",
    error: d.last_error ?? "",
    lag: Math.round(d.lag_s ?? 0),
    period: Math.round(d.period_s ?? 0),
    age: Math.round(d.updated_age_s ?? d.age_s ?? 0),
  });
  return text === key ? item.reason : text;
}

/** Seconds as "3 d 4 h", "2 h 5 min", "5 min 3 s" or "12 s". */
export function durationText(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (days > 0) return `${days} d ${hours} h`;
  if (hours > 0) return `${hours} h ${minutes} min`;
  if (minutes > 0) return `${minutes} min ${total % 60} s`;
  return `${total} s`;
}

/** "label: value" lines for the facts an item carries (uptime, runs, errors, space, versions). */
export function detailLines(item: HealthItem, t: Translate): string[] {
  const d = item.details;
  const lines: string[] = [];
  const add = (key: string, value: string | number | null | undefined) => {
    if (value !== null && value !== undefined && value !== "") lines.push(`${t(key)}: ${value}`);
  };
  if (d.uptime_s != null) add("health.detail.uptime", durationText(d.uptime_s));
  add("health.detail.lastRun", d.last_run_utc);
  add("health.detail.lastSuccess", d.last_success_utc);
  add("health.detail.lastError", d.last_error_utc);
  if (d.overrun_count !== undefined) add("health.detail.overruns", d.overrun_count);
  if (d.lag_s != null) add("health.detail.lag", durationText(d.lag_s));
  if (d.age_s != null && item.group !== "audit") add("health.detail.beatAge", durationText(d.age_s));
  add("health.detail.lastWrite", d.last_write_utc);
  if (d.free_bytes !== undefined && d.total_bytes !== undefined) {
    add("health.detail.free", `${(d.free_bytes / GIB).toFixed(1)} / ${(d.total_bytes / GIB).toFixed(1)} GiB`);
  }
  if (d.versions) {
    add("health.detail.versions", Object.entries(d.versions).map(([name, v]) => `${name} ${v ?? "–"}`).join(", "));
  }
  return lines;
}

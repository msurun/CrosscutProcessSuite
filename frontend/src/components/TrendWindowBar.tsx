// frontend/src/components/TrendWindowBar.tsx
// Toolbar that edits one TrendWindow: relative/absolute mode, width presets, custom width,
// back/forward panning, live refresh and absolute start/end. Pure view: all maths is in trendWindow.ts.
import { useState } from "react";

import type { Translate } from "../findings";
import {
  MS_PER_SECOND,
  NS_PER_MS,
  WIDTH_PRESETS_S,
  isLive,
  panWindow,
  resolveWindow,
  validateWindow,
  withWidth,
} from "../trendWindow";
import type { TrendWindow } from "../trendWindow";

/** Props of the toolbar; `dataEndNs` anchors "now" to the end of the data when known. */
export interface TrendWindowBarProps {
  t: Translate;
  window: TrendWindow;
  nowMs: number;
  dataEndNs?: number;
  onChange: (window: TrendWindow) => void;
}

/** Refresh periods offered for a live window, in seconds. */
const REFRESH_OPTIONS_S = [5, 10, 30, 60];
/** Seconds per custom-width unit. */
const UNIT_SECONDS: Record<string, number> = { minutes: 60, hours: 3600, days: 86400 };
/** Default refresh period when live is switched on, in seconds. */
const DEFAULT_REFRESH_S = 10;
/** Maps the English messages of validateWindow to catalogue keys. */
const PROBLEM_KEYS: Record<string, string> = {
  "Relative window must be at least 60 seconds.": "trendWindow.problem.too_short",
  "Invalid start time.": "trendWindow.problem.bad_start",
  "Invalid end time.": "trendWindow.problem.bad_end",
  "End time must be after start time.": "trendWindow.problem.end_before_start",
};

/**
 * ISO UTC string -> value for <input type="datetime-local">, which is a local wall-clock time
 * without zone ("YYYY-MM-DDTHH:mm"). Shifting by the zone offset makes toISOString print local digits.
 */
export function utcToLocalInput(iso: string): string {
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return "";
  const shifted = new Date(ms - new Date(ms).getTimezoneOffset() * 60_000);
  return shifted.toISOString().slice(0, 16);
}

/** Local wall-clock input value -> ISO UTC. new Date("YYYY-MM-DDTHH:mm") is parsed as local time. */
export function localInputToUtc(value: string): string | null {
  const ms = new Date(value).getTime();
  return Number.isNaN(ms) ? null : new Date(ms).toISOString();
}

/** Absolute window covering the range the given window currently shows. */
function toAbsolute(w: TrendWindow, nowMs: number, dataEndNs?: number): TrendWindow {
  const { startNs, endNs } = resolveWindow(w, nowMs, dataEndNs);
  return {
    kind: "absolute",
    start_utc: new Date(startNs / NS_PER_MS).toISOString(),
    end_utc: new Date(endNs / NS_PER_MS).toISOString(),
  };
}

/** Relative window of the same width as the given one (the width becomes last_s). */
function toRelative(w: TrendWindow, nowMs: number, dataEndNs?: number): TrendWindow {
  const { startNs, endNs } = resolveWindow(w, nowMs, dataEndNs);
  const seconds = Math.round((endNs - startNs) / (NS_PER_MS * MS_PER_SECOND));
  return { kind: "relative", last_s: seconds };
}

function ModeToggle({ t, window: w, onSelect }: { t: Translate; window: TrendWindow; onSelect: (kind: TrendWindow["kind"]) => void }) {
  return (
    <>
      {(["relative", "absolute"] as const).map((kind) => (
        <button key={kind} type="button" aria-pressed={w.kind === kind} onClick={() => w.kind !== kind && onSelect(kind)}>
          {t(`trendWindow.mode.${kind}`)}
        </button>
      ))}
    </>
  );
}

function PresetButtons({ window: w, onPick }: { window: TrendWindow; onPick: (seconds: number) => void }) {
  return (
    <>
      {WIDTH_PRESETS_S.map((preset) => (
        <button
          key={preset.id}
          type="button"
          aria-pressed={w.kind === "relative" && w.last_s === preset.seconds}
          onClick={() => onPick(preset.seconds)}
        >
          {preset.id}
        </button>
      ))}
    </>
  );
}

function CustomWidth({ t, onApply }: { t: Translate; onApply: (seconds: number) => void }) {
  const [amount, setAmount] = useState("");
  const [unit, setUnit] = useState("hours");
  const seconds = Number(amount) * UNIT_SECONDS[unit];
  return (
    <span>
      <input type="number" min={1} aria-label={t("trendWindow.customAmount")} value={amount} onChange={(e) => setAmount(e.target.value)} />
      <select aria-label={t("trendWindow.customUnit")} value={unit} onChange={(e) => setUnit(e.target.value)}>
        {Object.keys(UNIT_SECONDS).map((u) => (
          <option key={u} value={u}>
            {t(`trendWindow.unit.${u}`)}
          </option>
        ))}
      </select>
      <button type="button" disabled={!(seconds > 0)} onClick={() => onApply(seconds)}>
        {t("trendWindow.apply")}
      </button>
    </span>
  );
}

function AbsoluteInputs({ t, window: w, onChange }: { t: Translate; window: TrendWindow; onChange: (w: TrendWindow) => void }) {
  if (w.kind !== "absolute") return null;
  // An unparsable (cleared) field is ignored, so the window never holds a non-date string.
  const edit = (field: "start_utc" | "end_utc") => (e: React.ChangeEvent<HTMLInputElement>) => {
    const iso = localInputToUtc(e.target.value);
    if (iso) onChange({ ...w, [field]: iso });
  };
  return (
    <>
      <label>
        {t("trendWindow.start")}
        <input type="datetime-local" value={utcToLocalInput(w.start_utc)} onChange={edit("start_utc")} />
      </label>
      <label>
        {t("trendWindow.end")}
        <input type="datetime-local" value={utcToLocalInput(w.end_utc)} onChange={edit("end_utc")} />
      </label>
    </>
  );
}

function LiveControls({ t, window: w, onChange }: { t: Translate; window: TrendWindow; onChange: (w: TrendWindow) => void }) {
  if (w.kind !== "relative") return null;
  const refresh = w.refresh_s ?? DEFAULT_REFRESH_S;
  return (
    <>
      <label>
        <input
          type="checkbox"
          checked={isLive(w)}
          onChange={(e) => onChange({ ...w, live: e.target.checked, refresh_s: refresh })}
        />
        {t("trendWindow.live")}
      </label>
      <select aria-label={t("trendWindow.refresh")} value={refresh} onChange={(e) => onChange({ ...w, refresh_s: Number(e.target.value) })}>
        {REFRESH_OPTIONS_S.map((s) => (
          <option key={s} value={s}>
            {t("trendWindow.refreshOption", { seconds: s })}
          </option>
        ))}
      </select>
    </>
  );
}

/** One toolbar editing a TrendWindow; every change is reported as a whole new window. */
export function TrendWindowBar({ t, window: w, nowMs, dataEndNs, onChange }: TrendWindowBarProps) {
  const setWidth = (seconds: number) => onChange(withWidth(w, seconds, nowMs, dataEndNs));
  const setMode = (kind: TrendWindow["kind"]) =>
    onChange(kind === "absolute" ? toAbsolute(w, nowMs, dataEndNs) : toRelative(w, nowMs, dataEndNs));
  const problems = validateWindow(w);
  return (
    <div role="group" aria-label={t("trendWindow.title")}>
      <ModeToggle t={t} window={w} onSelect={setMode} />
      <PresetButtons window={w} onPick={setWidth} />
      <CustomWidth t={t} onApply={setWidth} />
      <AbsoluteInputs t={t} window={w} onChange={onChange} />
      <button type="button" onClick={() => onChange(panWindow(w, -1, nowMs, dataEndNs))}>
        {t("trendWindow.back")}
      </button>
      <button type="button" onClick={() => onChange(panWindow(w, 1, nowMs, dataEndNs))}>
        {t("trendWindow.forward")}
      </button>
      <LiveControls t={t} window={w} onChange={onChange} />
      <div role="status">{problems.map((p) => t(PROBLEM_KEYS[p] ?? "trendWindow.problem.unknown")).join(" ")}</div>
    </div>
  );
}

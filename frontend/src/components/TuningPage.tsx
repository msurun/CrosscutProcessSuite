// src/components/TuningPage.tsx
/**
 * Tuning page: suggests a step-test window, reports the identified process model,
 * and exposes PI settings / DCS forms for the selected loop.
 *
 * The page is read-only: it never writes to the plant, it only displays what the
 * backend computed and lets the engineer copy the settings out.
 */
import { useEffect, useState } from "react";

import {
  fetchTuning,
  type LoopSummary,
  type TuningPayload,
} from "../api";
import type { Translate } from "../findings";
import { formatFixed } from "../format";
import { DcsForms, PiSettingsTable, formatNumber } from "./SettingsTables";
import { CurrentSettingsCompare } from "./CurrentSettingsCompare";
import { StatusChip } from "./StatusChip";
import { Stepper, type StepInfo } from "./Stepper";
import { TrendPane } from "./TrendPane";
import { WindowPicker } from "./WindowPicker";

/** Milliseconds the robustness slider must stay still before a refetch. */
const ROBUSTNESS_DEBOUNCE_MS = 250;

/** Slider bounds; 0 means "fast" tuning, 1 means "smooth" tuning. */
const ROBUSTNESS_MIN = 0;
const ROBUSTNESS_MAX = 1;
const ROBUSTNESS_STEP = 0.05;
const ROBUSTNESS_DEFAULT = 0.5;

/** Seconds per minute, used to render window bounds as rounded minutes. */
const SECONDS_PER_MINUTE = 60;

type TuningStatus = "loading" | "ready" | "error";

/** Selected analysis window; `null` asks the backend for its best suggestion. */
type TuningWindow = { startS: number; endS: number } | null;

type TuningPageProps = {
  datasetId: string;
  loopName: string;
  /** The loop being tuned; its tags and unit feed the window picker and the units on the page. */
  loop: LoopSummary;
  t: Translate;
  onBack: () => void;
};

/**
 * Loads the tuning payload, keeping the previous one visible while the next
 * request is in flight so the page never flashes back to a blank state.
 *
 * Returns the latest payload, a coarse status and, when it failed, the reason
 * string meant to be shown to the user.
 */
function useTuning(
  datasetId: string,
  loopName: string,
  window: TuningWindow,
  robustness: number
): { payload: TuningPayload | null; status: TuningStatus; errorReason: string } {
  const [payload, setPayload] = useState<TuningPayload | null>(null);
  const [status, setStatus] = useState<TuningStatus>("loading");
  const [errorReason, setErrorReason] = useState("");

  const startS = window?.startS;
  const endS = window?.endS;

  useEffect(() => {
    let cancelled = false;
    const options = startS !== undefined && endS !== undefined ? { startS, endS, robustness } : { robustness };

    fetchTuning(datasetId, loopName, options)
      .then((result) => {
        if (cancelled) return;
        setPayload(result);
        setStatus("ready");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setErrorReason(error instanceof Error ? error.message : String(error));
        setStatus("error");
      });

    return () => {
      cancelled = true;
    };
  }, [datasetId, loopName, startS, endS, robustness]);

  return { payload, status, errorReason };
}

/**
 * Mirrors `value` after the slider has stopped moving for the debounce delay.
 * Lets the user drag smoothly without firing one request per pixel.
 */
function useDebouncedValue(value: number, delayMs: number): number {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}

/** Renders seconds as whole minutes for the window labels. */
function toMinutes(seconds: number): number {
  return Math.round(seconds / SECONDS_PER_MINUTE);
}

/** Maps a fit verdict to the colour level expected by `StatusChip`. */
function fitVerdictLevel(verdict: "good" | "fair" | "poor"): "ok" | "warning" | "problem" {
  if (verdict === "good") return "ok";
  if (verdict === "fair") return "warning";
  return "problem";
}

/** Triggers a browser download of the tuning report as Markdown. */
function downloadMarkdown(markdown: string, fileName: string): void {
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  anchor.click();
  URL.revokeObjectURL(url);
}

/** Step 1: pick one of the backend's suggested windows, or keep the automatic one. */
function WindowStep({
  datasetId,
  loop,
  payload,
  window,
  onSelectWindow,
  t,
}: {
  datasetId: string;
  loop: LoopSummary;
  payload: TuningPayload;
  window: TuningWindow;
  onSelectWindow: (window: TuningWindow) => void;
  t: Translate;
}) {
  const current = payload.window;

  return (
    <section className="tuning-step">
      <h3>{t("tuning.step1")}</h3>
      {payload.windows.length === 0 ? (
        <p className="status">{t("tuning.window.none")}</p>
      ) : (
        <p>{t("tuning.window.suggested")}</p>
      )}
      {payload.windows.map((suggestion) => (
        <button
          key={`${suggestion.start_s}-${suggestion.end_s}`}
          type="button"
          className="filter-chip"
          aria-pressed={
            window !== null && window.startS === suggestion.start_s && window.endS === suggestion.end_s
          }
          onClick={() => onSelectWindow({ startS: suggestion.start_s, endS: suggestion.end_s })}
        >
          {t("tuning.window.range", {
            start: toMinutes(suggestion.start_s),
            end: toMinutes(suggestion.end_s),
          })}
        </button>
      ))}
      <p>
        {t("tuning.window.current", {
          start: toMinutes(current.start_s),
          end: toMinutes(current.end_s),
          manual: current.manual_percent,
        })}
      </p>
      <WindowPicker
        datasetId={datasetId}
        loop={loop}
        window={window ?? { startS: current.start_s, endS: current.end_s }}
        onSelectWindow={onSelectWindow}
        t={t}
      />
    </section>
  );
}

/** Step 2: warnings, model fit verdict, key numbers and the check overlay. */
function ModelStep({ payload, unit, t }: { payload: TuningPayload; unit: string; t: Translate }) {
  const checkData = payload.check
    ? [payload.check.t_s, payload.check.measured, payload.check.simulated]
    : null;

  return (
    <section className="tuning-step">
      <h3>{t("tuning.step2")}</h3>
      {payload.warnings.map((code) => (
        <p key={code} className="status status-error">
          {t(`tuning.warning.${code}`)}
        </p>
      ))}
      {payload.blocked_code !== null && (
        <p className="status status-error">{t(`tuning.blocked.${payload.blocked_code}`)}</p>
      )}
      {payload.fit !== null && (
        <StatusChip
          level={fitVerdictLevel(payload.fit.verdict)}
          label={t(`tuning.fit.${payload.fit.verdict}`, { r2: formatFixed(payload.fit.r_squared, 2) })}
        />
      )}
      {payload.model !== null && (
        <dl className="key-numbers">
          <dt>{t("tuning.model.gain")}</dt>
          <dd>
            {formatNumber(payload.model.gain)}{" "}
            <span className="unit">{t("tuning.model.gainUnit", { unit })}</span>
          </dd>
          <dt>{t("tuning.model.tau")}</dt>
          <dd>{t("tuning.model.seconds", { value: formatNumber(payload.model.time_constant_s) })}</dd>
          <dt>{t("tuning.model.delay")}</dt>
          <dd>{t("tuning.model.seconds", { value: formatNumber(payload.model.delay_s) })}</dd>
          <dt>{t("tuning.model.ratio")}</dt>
          <dd>{formatFixed(payload.model.delay_s / payload.model.time_constant_s, 2)}</dd>
        </dl>
      )}
      {payload.model !== null && (
        <p className="hint">{t(ratioHintKey(payload.model.delay_s / payload.model.time_constant_s))}</p>
      )}
      {checkData !== null && (
        <TrendPane
          data={checkData}
          labels={[t("tuning.check.measured"), t("tuning.check.model")]}
          colors={["--series-1", "--series-2"]}
          height={200}
          syncKey="tuning-check"
          xIsTime={false}
          xLabel={t("tuning.check.xLabel")}
        />
      )}
    </section>
  );
}

/** Slider whose left end tunes fast and whose right end tunes smooth. */
function RobustnessSlider({
  value,
  onChange,
  t,
}: {
  value: number;
  onChange: (value: number) => void;
  t: Translate;
}) {
  return (
    <div className="robustness">
      <label htmlFor="robustness-range">{t("tuning.robustness")}</label>
      <span className="hint">{t("tuning.robustness.fast")}</span>
      <input
        id="robustness-range"
        type="range"
        min={ROBUSTNESS_MIN}
        max={ROBUSTNESS_MAX}
        step={ROBUSTNESS_STEP}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
      <span className="hint">{t("tuning.robustness.smooth")}</span>
    </div>
  );
}

/** Step 3: robustness trade-off, PI settings, step preview, DCS forms and export. */
function SettingsStep({
  payload,
  robustness,
  onRobustnessChange,
  datasetId,
  loopName,
  unit,
  t,
}: {
  payload: TuningPayload;
  robustness: number;
  onRobustnessChange: (value: number) => void;
  datasetId: string;
  loopName: string;
  unit: string;
  t: Translate;
}) {
  const settings = payload.settings;
  if (settings === null) return null;
  if (payload.blocked_code !== null) return null;

  const pvData = payload.step ? [payload.step.t_s, payload.step.pv] : null;
  const outData = payload.step ? [payload.step.t_s, payload.step.out] : null;
  const fitText =
    payload.fit === null
      ? ""
      : t(`tuning.fit.${payload.fit.verdict}`, { r2: formatFixed(payload.fit.r_squared, 2) });

  return (
    <section className="tuning-step">
      <h3>{t("tuning.step3")}</h3>
      <p className="recommendation" role="status">
        {t("tuning.recommendation", {
          kc: formatNumber(settings.simc.kc),
          ti: formatNumber(settings.simc.ti_s),
          fit: fitText,
        })}
      </p>
      <RobustnessSlider value={robustness} onChange={onRobustnessChange} t={t} />
      <PiSettingsTable settings={settings} t={t} />
      <CurrentSettingsCompare storageKey={`crosscut.currentSettings.${datasetId}.${loopName}`} settings={settings} t={t} />
      {pvData !== null && outData !== null && (
        <>
          <p>{t("tuning.preview")}</p>
          <TrendPane
            data={pvData}
            labels={[t("tuning.preview.pvPane")]}
            colors={["--series-1"]}
            unit={unit}
            height={160}
            syncKey="tuning-step"
            xIsTime={false}
            xLabel={t("tuning.preview.xLabel")}
          />
          <TrendPane
            data={outData}
            labels={[t("tuning.preview.outPane")]}
            colors={["--series-3"]}
            unit="%"
            height={160}
            syncKey="tuning-step"
            xIsTime={false}
            xLabel={t("tuning.preview.xLabel")}
          />
        </>
      )}
      <h4>{t("tuning.dcs")}</h4>
      <DcsForms forms={payload.dcs_forms} t={t} />
      <button
        type="button"
        className="filter-chip"
        onClick={() => downloadMarkdown(payload.markdown, `tuning-${loopName}.md`)}
      >
        {t("tuning.export")}
      </button>
    </section>
  );
}

/** Controllability class from the dead time / time constant ratio (a common rule of thumb). */
const RATIO_EASY_BELOW = 0.3;
const RATIO_MEDIUM_BELOW = 1;

/** Locale key of the plain-language hint for a dead-time / time-constant ratio. */
function ratioHintKey(ratio: number): string {
  if (ratio < RATIO_EASY_BELOW) return "tuning.model.ratioEasy";
  if (ratio < RATIO_MEDIUM_BELOW) return "tuning.model.ratioMedium";
  return "tuning.model.ratioHard";
}

/** State of the three wizard steps, derived from what the backend returned. */
function buildSteps(payload: TuningPayload, t: Translate): StepInfo[] {
  const blocked = payload.blocked_code !== null || payload.settings === null;
  const modelBlocked = payload.blocked_code !== null || payload.fit?.verdict === "poor";
  return [
    {
      id: "window",
      label: t("tuning.stepper.window"),
      state: "done",
      detail: t("tuning.window.range", {
        start: toMinutes(payload.window.start_s),
        end: toMinutes(payload.window.end_s),
      }),
    },
    {
      id: "model",
      label: t("tuning.stepper.model"),
      state: modelBlocked ? "blocked" : "done",
      detail: payload.fit === null ? undefined : formatFixed(payload.fit.r_squared, 2),
    },
    { id: "settings", label: t("tuning.stepper.settings"), state: blocked ? "blocked" : "active" },
  ];
}

/** Full tuning page for one loop: window picker, model report and settings. */
export function TuningPage({ datasetId, loopName, loop, t, onBack }: TuningPageProps) {
  const [window, setWindow] = useState<TuningWindow>(null);
  const [robustness, setRobustness] = useState(ROBUSTNESS_DEFAULT);
  const appliedRobustness = useDebouncedValue(robustness, ROBUSTNESS_DEBOUNCE_MS);

  const { payload, status, errorReason } = useTuning(datasetId, loopName, window, appliedRobustness);

  return (
    <>
      <button type="button" className="link-button" onClick={onBack}>
        ← {t("loops.back")}
      </button>
      <h2>
        {t("tuning.title")}
      </h2>
      {status === "loading" && payload === null && <p className="status">{t("trends.loading")}</p>}
      {status === "error" && <p className="status status-error">{t("trends.error", { reason: errorReason })}</p>}
      <p className="banner" role="note">
        {t("tuning.banner")}
      </p>
      {payload !== null && (
        <>
          <Stepper
            steps={buildSteps(payload, t)}
            ariaLabel={t("tuning.stepper")}
            stateLabels={{
              todo: t("tuning.stepState.todo"),
              active: t("tuning.stepState.active"),
              done: t("tuning.stepState.done"),
              blocked: t("tuning.stepState.blocked"),
            }}
          />
          <WindowStep
            datasetId={datasetId}
            loop={loop}
            payload={payload}
            window={window}
            onSelectWindow={setWindow}
            t={t}
          />
          <ModelStep payload={payload} unit={loop.unit} t={t} />
          <SettingsStep
            payload={payload}
            robustness={robustness}
            onRobustnessChange={setRobustness}
            datasetId={datasetId}
            loopName={loopName}
            unit={loop.unit}
            t={t}
          />
        </>
      )}
    </>
  );
}

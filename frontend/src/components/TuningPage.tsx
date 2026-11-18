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
  type FopdtModel,
  type LoopSummary,
  type TuningOptions,
  type TuningPayload,
} from "../api";
import type { Translate } from "../findings";
import { formatFixed } from "../format";
import { isIpdtModel, parseSwing } from "../tuningIpdt";
import { DcsForms, PiSettingsTable, VendorBlock, formatNumber } from "./SettingsTables";
import { CurrentSettingsCompare } from "./CurrentSettingsCompare";
import { StatusChip } from "./StatusChip";
import { Stepper, type StepInfo } from "./Stepper";
import { IpdtModelView, IpdtRecommendation, IpdtRefusal, SwingInputs, TuningWarnings } from "./TuningIpdt";
import { TrendPane } from "./TrendPane";
import { TuningProposeButton } from "./TuningProposeButton";
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
  /** Called after the process kind was saved from a warning, so the loop list can reload. */
  onKnowledgeSaved?: () => void;
};

/** Averaging-level inputs as typed by the user (both empty = not used). */
type SwingText = { max: string; load: string };

/** Request options for the current window, robustness and (valid) averaging-level pair. */
function requestOptions(window: TuningWindow, robustness: number, swing: SwingText): TuningOptions {
  const options: TuningOptions = { robustness };
  if (window !== null) Object.assign(options, { startS: window.startS, endS: window.endS });
  const input = parseSwing(swing.max, swing.load);
  if (input.state === "valid") Object.assign(options, { maxSwing: input.maxSwing, loadStepPct: input.loadStepPct });
  return options;
}

/**
 * Loads the tuning payload, keeping the previous one visible while the next
 * request is in flight so the page never flashes back to a blank state.
 *
 * Returns the latest payload, a coarse status and, when it failed, the reason
 * string meant to be shown to the user. Changing `reloadKey` forces a refetch.
 */
function useTuning(
  datasetId: string,
  loopName: string,
  request: { window: TuningWindow; robustness: number; swing: SwingText; reloadKey: number }
): { payload: TuningPayload | null; status: TuningStatus; errorReason: string } {
  const [payload, setPayload] = useState<TuningPayload | null>(null);
  const [status, setStatus] = useState<TuningStatus>("loading");
  const [errorReason, setErrorReason] = useState("");

  const { window, robustness, swing, reloadKey } = request;
  const startS = window?.startS;
  const endS = window?.endS;

  useEffect(() => {
    let cancelled = false;
    const options = requestOptions(startS === undefined || endS === undefined ? null : { startS, endS }, robustness, swing);

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
  }, [datasetId, loopName, startS, endS, robustness, swing.max, swing.load, reloadKey]);

  return { payload, status, errorReason };
}

/**
 * Mirrors `value` after it has stopped changing for the debounce delay.
 * Lets the user drag a slider or type without firing one request per change.
 */
function useDebouncedValue<T>(value: T, delayMs: number): T {
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

type WindowStepProps = {
  datasetId: string;
  loop: LoopSummary;
  payload: TuningPayload;
  window: TuningWindow;
  onSelectWindow: (window: TuningWindow) => void;
  t: Translate;
};

/** The suggested-window chips, or a note when the backend found none. */
function WindowSuggestions({ payload, window, onSelectWindow, t }: Omit<WindowStepProps, "datasetId" | "loop">) {
  return (
    <>
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
    </>
  );
}

/** Description of the window in use, plus the padding note when the backend padded it. */
function CurrentWindowInfo({ current, t }: { current: TuningPayload["window"]; t: Translate }) {
  return (
    <>
      <p>
        {t("tuning.window.current", {
          start: toMinutes(current.start_s),
          end: toMinutes(current.end_s),
          manual: current.manual_percent,
        })}
      </p>
      {current.padded.before_s + current.padded.after_s > 0 && (
        <p className="hint">
          {t("tuning.window.padded", {
            before: Math.round(current.padded.before_s),
            after: Math.round(current.padded.after_s),
          })}
        </p>
      )}
    </>
  );
}

/** Step 1: pick one of the backend's suggested windows, or keep the automatic one. */
function WindowStep({ datasetId, loop, payload, window, onSelectWindow, t }: WindowStepProps) {
  const current = payload.window;

  return (
    <section className="tuning-step">
      <h3>{t("tuning.step1")}</h3>
      <WindowSuggestions payload={payload} window={window} onSelectWindow={onSelectWindow} t={t} />
      <CurrentWindowInfo current={current} t={t} />
      <WindowPicker
        datasetId={datasetId}
        loop={loop}
        window={window ?? { startS: current.start_s, endS: current.end_s }}
        fitCurve={payload.fit_curve ?? null}
        onSelectWindow={onSelectWindow}
        t={t}
      />
    </section>
  );
}

/** The model numbers of a FOPDT loop and the controllability hint. */
function FopdtModelView({ model, unit, t }: { model: FopdtModel; unit: string; t: Translate }) {
  return (
    <>
      <dl className="key-numbers">
        <dt>{t("tuning.model.gain")}</dt>
        <dd>
          {formatNumber(model.gain)} <span className="unit">{t("tuning.model.gainUnit", { unit })}</span>
        </dd>
        <dt>{t("tuning.model.tau")}</dt>
        <dd>{t("tuning.model.seconds", { value: formatNumber(model.time_constant_s) })}</dd>
        <dt>{t("tuning.model.delay")}</dt>
        <dd>{t("tuning.model.seconds", { value: formatNumber(model.delay_s) })}</dd>
        <dt>{t("tuning.model.ratio")}</dt>
        <dd>{formatFixed(model.delay_s / model.time_constant_s, 2)}</dd>
      </dl>
      <p className="hint">{t(ratioHintKey(model.delay_s / model.time_constant_s))}</p>
    </>
  );
}

/** Data of the check chart: measured PV against the model (the fitted ramp for integrating loops). */
function checkChartData(payload: TuningPayload): (number | null)[][] | null {
  if (!payload.check) return null;
  const { t_s, measured, simulated } = payload.check;
  const curve = payload.fit_curve;
  const model = curve && curve.pv_model.length === t_s.length ? curve.pv_model : simulated;
  return [t_s, measured, model];
}

/** Error block for a blocked tuning run (IPDT refusal gets its own view). */
function BlockedNotice({ payload, t }: { payload: TuningPayload; t: Translate }) {
  if (payload.blocked_code === "ipdt_refused") {
    return <IpdtRefusal reasons={payload.blocked_reasons ?? []} t={t} />;
  }
  if (payload.blocked_code === null) return null;
  return <p className="status status-error">{t(`tuning.blocked.${payload.blocked_code}`)}</p>;
}

/** Chip with the model fit verdict, when a fit exists. */
function FitChip({ payload, t }: { payload: TuningPayload; t: Translate }) {
  if (payload.fit === null) return null;
  return (
    <StatusChip
      level={fitVerdictLevel(payload.fit.verdict)}
      label={t(`tuning.fit.${payload.fit.verdict}`, { r2: formatFixed(payload.fit.r_squared, 2) })}
    />
  );
}

/** Measured PV against the model (or fitted ramp), when the backend sent a check. */
function CheckChart({ payload, ipdt, t }: { payload: TuningPayload; ipdt: boolean; t: Translate }) {
  const checkData = checkChartData(payload);
  if (checkData === null) return null;
  return (
    <TrendPane
      data={checkData}
      labels={[t("tuning.check.measured"), t(ipdt ? "tuning.check.ramp" : "tuning.check.model")]}
      colors={["--series-1", "--series-2"]}
      height={200}
      syncKey="tuning-check"
      xIsTime={false}
      xLabel={t("tuning.check.xLabel")}
    />
  );
}

type ModelStepProps = {
  payload: TuningPayload;
  unit: string;
  swing: { text: SwingText; onChange: (max: string, load: string) => void };
  datasetId: string;
  loopName: string;
  actions: { onKindSaved: () => void };
  t: Translate;
};

/** Step 2: warnings, model fit verdict, key numbers and the check overlay. */
function ModelStep({ payload, unit, swing, datasetId, loopName, actions, t }: ModelStepProps) {
  const model = payload.model;
  const ipdt = isIpdtModel(model);

  return (
    <section className="tuning-step">
      <h3>{t("tuning.step2")}</h3>
      <TuningWarnings
        warnings={payload.warnings}
        datasetId={datasetId}
        loopName={loopName}
        onKindSaved={actions.onKindSaved}
        t={t}
      />
      <BlockedNotice payload={payload} t={t} />
      <FitChip payload={payload} t={t} />
      {model !== null && model.kind === "fopdt" && <FopdtModelView model={model} unit={unit} t={t} />}
      {ipdt && <IpdtModelView model={model} unit={unit} spanS={payload.window.end_s - payload.window.start_s} t={t} />}
      {ipdt && (
        <SwingInputs
          maxText={swing.text.max}
          loadText={swing.text.load}
          onChange={swing.onChange}
          tauC={payload.tau_c_s}
          unit={unit}
          t={t}
        />
      )}
      <CheckChart payload={payload} ipdt={ipdt} t={t} />
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

type PiSettings = NonNullable<TuningPayload["settings"]>;

/** Recommendation sentence (or the IPDT variant) with the fit verdict appended. */
function Recommendation({ payload, settings, t }: { payload: TuningPayload; settings: PiSettings; t: Translate }) {
  const fitText =
    payload.fit === null
      ? ""
      : t(`tuning.fit.${payload.fit.verdict}`, { r2: formatFixed(payload.fit.r_squared, 2) });
  if (isIpdtModel(payload.model)) {
    return <IpdtRecommendation payload={payload} settings={settings} fitText={fitText} t={t} />;
  }
  return (
    <p className="recommendation" role="status">
      {t("tuning.recommendation", {
        kc: formatNumber(settings.simc.kc),
        ti: formatNumber(settings.simc.ti_s),
        fit: fitText,
      })}
    </p>
  );
}

/** Simulated closed-loop step response: PV and controller output panes. */
function StepPreview({ payload, unit, t }: { payload: TuningPayload; unit: string; t: Translate }) {
  if (!payload.step) return null;
  const pvData = [payload.step.t_s, payload.step.pv];
  const outData = [payload.step.t_s, payload.step.out];
  return (
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
  );
}

type SettingsStepProps = {
  payload: TuningPayload;
  robustness: number;
  onRobustnessChange: (value: number) => void;
  datasetId: string;
  loopName: string;
  unit: string;
  t: Translate;
};

/** Step 3: robustness trade-off, PI settings, step preview, DCS forms and export. */
function SettingsStep({ payload, robustness, onRobustnessChange, datasetId, loopName, unit, t }: SettingsStepProps) {
  const settings = payload.settings;
  if (settings === null) return null;
  if (payload.blocked_code !== null) return null;

  return (
    <section className="tuning-step">
      <h3>{t("tuning.step3")}</h3>
      <Recommendation payload={payload} settings={settings} t={t} />
      <RobustnessSlider value={robustness} onChange={onRobustnessChange} t={t} />
      <PiSettingsTable settings={settings} t={t} />
      <CurrentSettingsCompare storageKey={`crosscut.currentSettings.${datasetId}.${loopName}`} settings={settings} t={t} />
      <StepPreview payload={payload} unit={unit} t={t} />
      <h4>{t("tuning.dcs")}</h4>
      <DcsForms forms={payload.dcs_forms} t={t} />
      <VendorBlock payload={payload} t={t} />
      <button
        type="button"
        className="filter-chip"
        onClick={() => downloadMarkdown(payload.markdown, `tuning-${loopName}.md`)}
      >
        {t("tuning.export")}
      </button>
      {!isIpdtModel(payload.model) && (
        <TuningProposeButton
          ctx={{
            datasetId,
            loopName,
            vendor: payload.vendor,
            window: { start_s: payload.window.start_s, end_s: payload.window.end_s },
            robustness,
          }}
          t={t}
        />
      )}
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

/** Page state: selected window, robustness, averaging inputs and the loaded payload. */
function useTuningPage(datasetId: string, loopName: string, onKnowledgeSaved?: () => void) {
  const [window, setWindow] = useState<TuningWindow>(null);
  const [robustness, setRobustness] = useState(ROBUSTNESS_DEFAULT);
  const [swingText, setSwingText] = useState<SwingText>({ max: "", load: "" });
  const [reloadKey, setReloadKey] = useState(0);
  const appliedRobustness = useDebouncedValue(robustness, ROBUSTNESS_DEBOUNCE_MS);
  const appliedMax = useDebouncedValue(swingText.max, ROBUSTNESS_DEBOUNCE_MS);
  const appliedLoad = useDebouncedValue(swingText.load, ROBUSTNESS_DEBOUNCE_MS);

  const loaded = useTuning(datasetId, loopName, {
    window,
    robustness: appliedRobustness,
    swing: { max: appliedMax, load: appliedLoad },
    reloadKey,
  });
  const onKindSaved = (): void => {
    setReloadKey((key) => key + 1);
    onKnowledgeSaved?.();
  };

  return { ...loaded, window, setWindow, robustness, setRobustness, swingText, setSwingText, onKindSaved };
}

type TuningPageState = ReturnType<typeof useTuningPage>;

/** Wizard progress indicator with localised step states. */
function TuningStepper({ payload, t }: { payload: TuningPayload; t: Translate }) {
  return (
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
  );
}

/** The stepper and the three wizard steps, shown once a payload exists. */
type TuningStepsProps = {
  payload: TuningPayload;
  state: TuningPageState;
  props: Pick<TuningPageProps, "datasetId" | "loopName" | "loop" | "t">;
};

function TuningSteps({ payload, state, props }: TuningStepsProps) {
  const { datasetId, loopName, loop, t } = props;
  return (
    <>
      <TuningStepper payload={payload} t={t} />
      <WindowStep
        datasetId={datasetId}
        loop={loop}
        payload={payload}
        window={state.window}
        onSelectWindow={state.setWindow}
        t={t}
      />
      <ModelStep
        payload={payload}
        unit={loop.unit}
        swing={{ text: state.swingText, onChange: (max, load) => state.setSwingText({ max, load }) }}
        datasetId={datasetId}
        loopName={loopName}
        actions={{ onKindSaved: state.onKindSaved }}
        t={t}
      />
      <SettingsStep
        payload={payload}
        robustness={state.robustness}
        onRobustnessChange={state.setRobustness}
        datasetId={datasetId}
        loopName={loopName}
        unit={loop.unit}
        t={t}
      />
    </>
  );
}

/** Full tuning page for one loop: window picker, model report and settings. */
export function TuningPage({ datasetId, loopName, loop, t, onBack, onKnowledgeSaved }: TuningPageProps) {
  const state = useTuningPage(datasetId, loopName, onKnowledgeSaved);
  const { payload, status, errorReason } = state;

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
      {payload !== null && <TuningSteps payload={payload} state={state} props={{ datasetId, loopName, loop, t }} />}
    </>
  );
}

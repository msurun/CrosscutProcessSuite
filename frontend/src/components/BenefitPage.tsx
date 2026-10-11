// src/components/BenefitPage.tsx
import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchBenefit, type BenefitPayload } from "../api";
import type { Translate } from "../findings";
import { TrendPane } from "./TrendPane";
import { formatNumber } from "./SettingsTables";

/** Delay before the typed inputs are sent to the server, in milliseconds. */
const DEBOUNCE_MS = 400;

/** Default value for the "value per unit per hour" field, in currency units. */
const DEFAULT_VALUE_PER_UNIT_H = "0";

/** Default safety margin in standard deviations. */
const DEFAULT_MARGIN_SIGMAS = "2";

/** Default fraction of variability removed, between 0 and 1. */
const DEFAULT_STD_REDUCTION = "0.5";

/** Upper bound of the variability-cut slider; 1.0 would mean a zero-width interval. */
const REDUCTION_SLIDER_MAX = 0.9;

/** Step of the variability-cut slider. */
const REDUCTION_SLIDER_STEP = 0.05;

/** Height of the benefit chart in pixels. */
const CHART_HEIGHT_PX = 220;

/** Key that keeps the benefit chart's x-axis in sync with itself across rerenders. */
const CHART_SYNC_KEY = "benefit";

/** CSS variable names used by the trend chart. */
const CURVE_COLOR_NOW = "--series-1";
const CURVE_COLOR_AFTER = "--series-3";

/** What the user typed, as raw strings, so partial input like "-" is not lost. */
export type BenefitInputStrings = {
  limit: string;
  side: "upper" | "lower";
  value: string;
  margin: string;
  reduction: string;
};

/** Fields actually sent to the API; a field is omitted when its input is not a number. */
type BenefitRequestInputs = {
  limit?: number;
  side: "upper" | "lower";
  valuePerUnitH?: number;
  marginSigmas?: number;
  stdReduction?: number;
};

/** Initial form values: the server chooses the limit, the rest are the documented defaults. */
const INITIAL_INPUTS: BenefitInputStrings = {
  limit: "",
  side: "upper",
  value: DEFAULT_VALUE_PER_UNIT_H,
  margin: DEFAULT_MARGIN_SIGMAS,
  reduction: DEFAULT_STD_REDUCTION,
};

/**
 * Parses a numeric form field.
 *
 * Returns undefined when the text is empty or does not parse, which means "do not send this
 * field to the server" and lets the backend fall back to its own default.
 */
function parseOptionalNumber(raw: string): number | undefined {
  if (raw.trim() === "") {
    return undefined;
  }
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : undefined;
}

/**
 * Turns the raw form strings into the payload the API expects.
 *
 * The limit is special: an empty string means "let the server choose".
 */
function toRequestInputs(inputs: BenefitInputStrings): BenefitRequestInputs {
  return {
    limit: parseOptionalNumber(inputs.limit),
    side: inputs.side,
    valuePerUnitH: parseOptionalNumber(inputs.value),
    marginSigmas: parseOptionalNumber(inputs.margin),
    stdReduction: parseOptionalNumber(inputs.reduction),
  };
}

/**
 * Runs a request against the benefit endpoint whenever the request inputs change.
 *
 * Keeps the previously loaded payload on screen while a new one is in flight, and only reports
 * "loading" before the very first payload arrives.
 */
function useBenefit(
  datasetId: string,
  loopName: string,
  applied: BenefitInputStrings,
): {
  payload: BenefitPayload | null;
  status: "loading" | "ready" | "error";
  errorReason: string;
} {
  const [payload, setPayload] = useState<BenefitPayload | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [errorReason, setErrorReason] = useState("");

  useEffect(() => {
    let isCancelled = false;
    fetchBenefit(datasetId, loopName, toRequestInputs(applied))
      .then((fresh) => {
        if (isCancelled) {
          return;
        }
        setPayload(fresh);
        setStatus("ready");
      })
      .catch((error: unknown) => {
        if (isCancelled) {
          return;
        }
        setErrorReason(error instanceof Error ? error.message : String(error));
        setStatus("error");
      });
    return () => {
      isCancelled = true;
    };
  }, [datasetId, loopName, applied]);

  return { payload, status, errorReason };
}

/**
 * Returns a copy of `inputs` that lags behind it by DEBOUNCE_MS.
 *
 * Typing therefore does not fire one request per keystroke.
 */
function useDebouncedInputs(inputs: BenefitInputStrings): BenefitInputStrings {
  const [applied, setApplied] = useState<BenefitInputStrings>(inputs);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => setApplied(inputs), DEBOUNCE_MS);
    return () => window.clearTimeout(timeoutId);
  }, [inputs]);

  return applied;
}

/** Downloads a markdown report as a file in the browser. */
function downloadMarkdown(fileName: string, markdown: string): void {
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  anchor.click();
  URL.revokeObjectURL(url);
}

/** One labelled form control with the "assumed" badge shown when the value is a default. */
function LabeledField({
  label,
  isAssumed,
  children,
}: {
  label: string;
  isAssumed: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="field">
      <span className="field-label">
        {label}
        {isAssumed ? <span className="badge">{"assumed"}</span> : null}
      </span>
      {children}
    </label>
  );
}

/** The limit field: blank means the server picks a value, which is then shown as a hint. */
function LimitField({
  inputs,
  payload,
  t,
  onChange,
}: {
  inputs: BenefitInputStrings;
  payload: BenefitPayload | null;
  t: Translate;
  onChange: (raw: string) => void;
}) {
  const unit = payload ? payload.unit : "";
  const placeholder = payload ? formatNumber(payload.assumptions.limit) : "";
  const showDefaultHint = payload !== null && payload.assumptions.limit_is_default && inputs.limit === "";

  return (
    <>
      <LabeledField label={t("benefit.limit", { unit })} isAssumed>
        <input type="number" step="any" placeholder={placeholder} value={inputs.limit} onChange={(e) => onChange(e.target.value)} />
      </LabeledField>
      {showDefaultHint ? (
        <p className="status status-error">
          {t("benefit.limit.default", {
            value: formatNumber(payload.assumptions.limit),
            unit: payload.unit,
          })}
        </p>
      ) : null}
    </>
  );
}

/** The upper/lower side selector. */
function SideField({
  side,
  t,
  onChange,
}: {
  side: "upper" | "lower";
  t: Translate;
  onChange: (side: "upper" | "lower") => void;
}) {
  return (
    <LabeledField label={t("benefit.side")} isAssumed>
      <select value={side} onChange={(e) => onChange(e.target.value === "lower" ? "lower" : "upper")}>
        <option value="upper">{t("benefit.side.upper")}</option>
        <option value="lower">{t("benefit.side.lower")}</option>
      </select>
    </LabeledField>
  );
}

/** The variability-cut slider, which shows its own current value next to the track. */
function ReductionField({
  reduction,
  t,
  onChange,
}: {
  reduction: string;
  t: Translate;
  onChange: (raw: string) => void;
}) {
  return (
    <LabeledField label={t("benefit.reduction")} isAssumed>
      <input
        type="range"
        min={0}
        max={REDUCTION_SLIDER_MAX}
        step={REDUCTION_SLIDER_STEP}
        value={reduction}
        onChange={(e) => onChange(e.target.value)}
      />
      <span className="field-value">{reduction}</span>
    </LabeledField>
  );
}

/** The form that drives the estimate. Changing any field schedules a new request. */
function InputsSection({
  inputs,
  payload,
  t,
  onChange,
}: {
  inputs: BenefitInputStrings;
  payload: BenefitPayload | null;
  t: Translate;
  onChange: (patch: Partial<BenefitInputStrings>) => void;
}) {
  return (
    <section>
      <h3>{t("benefit.inputs")}</h3>
      <LimitField inputs={inputs} payload={payload} t={t} onChange={(limit) => onChange({ limit })} />
      <SideField side={inputs.side} t={t} onChange={(side) => onChange({ side })} />
      <LabeledField label={t("benefit.value")} isAssumed>
        <input type="number" min={0} value={inputs.value} onChange={(e) => onChange({ value: e.target.value })} />
      </LabeledField>
      <LabeledField label={t("benefit.margin")} isAssumed>
        <input
          type="number"
          min={0}
          step={0.5}
          value={inputs.margin}
          onChange={(e) => onChange({ margin: e.target.value })}
        />
      </LabeledField>
      <ReductionField reduction={inputs.reduction} t={t} onChange={(reduction) => onChange({ reduction })} />
    </section>
  );
}

/** Formats the value-per-hour cell, or a dash when no unit value was provided. */
function valuePerHourText(payload: BenefitPayload): string {
  if (payload.assumptions.value_per_unit_h <= 0) {
    return "–";
  }
  return formatNumber(payload.estimate.value_per_h);
}

/** The key numbers of the estimate: how much room is left, and what it is worth. */
function ResultNumbers({ payload, t }: { payload: BenefitPayload; t: Translate }) {
  return (
    <dl className="key-numbers">
      <dt>{t("benefit.room")}</dt>
      <dd>{`${formatNumber(payload.estimate.shift)} ${payload.unit}`}</dd>
      <dt>{t("benefit.valuePerHour")}</dt>
      <dd>{valuePerHourText(payload)}</dd>
      <dt>{t("benefit.gap")}</dt>
      <dd>{`${formatNumber(payload.estimate.current_gap)} ${payload.unit}`}</dd>
    </dl>
  );
}

/** Any server notes about the estimate, shown as one error line per code. */
function NotesList({ notes, t }: { notes: string[]; t: Translate }) {
  return (
    <>
      {notes.map((code) => (
        <p key={code} className="status status-error">
          {t(`benefit.note.${code}`)}
        </p>
      ))}
    </>
  );
}

/** The right-hand section: estimate numbers, notes and the before/after chart. */
function ResultSection({ payload, t }: { payload: BenefitPayload; t: Translate }) {
  const chartData = useMemo(
    () => [payload.curves.x, payload.curves.now, payload.curves.after],
    [payload.curves],
  );

  return (
    <section>
      <h3>{t("benefit.result")}</h3>
      <ResultNumbers payload={payload} t={t} />
      <p>
        {t("benefit.std", {
          now: formatNumber(payload.estimate.std_now),
          target: formatNumber(payload.estimate.std_target),
        })}
      </p>
      <p className="hint">{t("benefit.samples", { count: payload.estimate.n_samples_used })}</p>
      <NotesList notes={payload.notes} t={t} />
      <p>{t("benefit.chart")}</p>
      <TrendPane
        data={chartData}
        labels={[t("benefit.curve.now"), t("benefit.curve.after")]}
        colors={[CURVE_COLOR_NOW, CURVE_COLOR_AFTER]}
        height={CHART_HEIGHT_PX}
        syncKey={CHART_SYNC_KEY}
        xIsTime={false}
        xLabel={t("benefit.chart.xLabel", { unit: payload.unit })}
      />
      <button
        type="button"
        className="filter-chip"
        onClick={() => downloadMarkdown(`benefit-${payload.loop}.md`, payload.markdown)}
      >
        {t("benefit.export")}
      </button>
    </section>
  );
}

/** Full-screen benefit analysis for one loop: input form on the left, estimate on the right. */
export function BenefitPage({
  datasetId,
  loopName,
  t,
  onBack,
}: {
  datasetId: string;
  loopName: string;
  t: Translate;
  onBack: () => void;
}) {
  const [inputs, setInputs] = useState<BenefitInputStrings>(INITIAL_INPUTS);
  const applied = useDebouncedInputs(inputs);
  const { payload, status, errorReason } = useBenefit(datasetId, loopName, applied);
  const patchInputs = useCallback(
    (patch: Partial<BenefitInputStrings>) => setInputs((previous) => ({ ...previous, ...patch })),
    [],
  );

  const isFirstLoad = payload === null && status === "loading" && errorReason === "";

  return (
    <>
      <button type="button" className="link-button" onClick={onBack}>
        ← {t("loops.back")}
      </button>
      <h2>
        {t("benefit.title")} – {loopName}
      </h2>
      <p className="status">{t("benefit.disclaimer")}</p>
      <div className="benefit-grid">
        <InputsSection inputs={inputs} payload={payload} t={t} onChange={patchInputs} />
        {payload !== null ? <ResultSection payload={payload} t={t} /> : null}
      </div>
      {isFirstLoad ? <p className="status">{t("trends.loading")}</p> : null}
      {status === "error" ? (
        <p className="status status-error">{t("trends.error", { reason: errorReason })}</p>
      ) : null}
    </>
  );
}

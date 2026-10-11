// src/components/InferencePanel.tsx
//
// "What if" panel for the fuzzy model: lets the user move each input with a
// slider and shows what the model infers from the resulting values.
//
// The component is intentionally split into small pieces:
//   - InputSliders   : the sliders, one per document input
//   - OutputShape    : the aggregated membership curve of one output
//   - WhyLine        : the sentence naming the rules that fired
//   - FiringList     : the firing strength of every rule
//
// All numbers are formatted with formatNumber (4 significant digits) so the
// panel never shows more precision than the model actually has.

import type { FuzzyDocument } from "../fuzzy";
import type { FuzzyInference } from "../api";
import type { Translate } from "../findings";
import { formatNumber } from "./SettingsTables";

/** Slider positions are (high - low) / 200, i.e. 201 possible stops. */
const SLIDER_STEPS = 200;

/** Geometry of the membership curve, in the 400 x 100 viewBox units. */
const PLOT_LEFT = 10;
const PLOT_RIGHT = 390;
const PLOT_TOP = 10;
const PLOT_BOTTOM = 90;

/** Thickness of the crisp-value marker line, in viewBox units. */
const CRISP_LINE_WIDTH = 2;

/** Opacity of the filled membership area. */
const AREA_OPACITY = 0.35;

/** Percentage ceiling used to turn a firing strength into a rounded percent. */
const PERCENT = 100;

/** Default slider position when a variable has no value yet: the middle. */
function sliderMiddle(low: number, high: number): number {
  return (low + high) / 2;
}

/** The label shown to the user: the variable label, or its id as a fallback. */
function variableName(variable: { id: string; label?: string }): string {
  return variable.label ?? variable.id;
}

/** Maps a value of the universe to an x coordinate inside the viewBox. */
function valueToX(value: number, low: number, high: number): number {
  if (high === low) {
    return PLOT_LEFT;
  }
  const ratio = (value - low) / (high - low);
  return PLOT_LEFT + ratio * (PLOT_RIGHT - PLOT_LEFT);
}

/** Maps a membership degree (0..1) to a y coordinate inside the viewBox. */
function degreeToY(degree: number): number {
  // y grows downwards, so degree 1 sits at the top and degree 0 at the bottom.
  return PLOT_BOTTOM - degree * (PLOT_BOTTOM - PLOT_TOP);
}

/** Builds the "x,y x,y ..." point list of the aggregated membership polygon. */
function areaPoints(universe: number[], aggregated: number[]): string {
  const points = universe.map((value, index) => {
    const x = valueToX(value, universe[0], universe[universe.length - 1]);
    const y = degreeToY(aggregated[index] ?? 0);
    return `${formatNumber(x)},${formatNumber(y)}`;
  });
  return `${PLOT_LEFT},${PLOT_BOTTOM} ${points.join(" ")} ${PLOT_RIGHT},${PLOT_BOTTOM}`;
}

/** Renders the rectangle of sliders, one field per document input. */
function InputSliders({
  document,
  values,
  onValues,
}: {
  document: FuzzyDocument;
  values: Record<string, number>;
  onValues: (next: Record<string, number>) => void;
}) {
  return (
    <>
      {document.inputs.map((input) => {
        const low = input.low ?? 0;
        const high = input.high ?? 1;
        const current = values[input.id] ?? sliderMiddle(low, high);
        return (
          <label className="field" key={input.id}>
            <span className="field-label">
              {variableName(input)}
              {input.unit ? ` (${input.unit})` : ""}
            </span>
            <input
              type="range"
              min={low}
              max={high}
              step={(high - low) / SLIDER_STEPS}
              value={current}
              onChange={(event) => onValues({ ...values, [input.id]: Number(event.target.value) })}
            />
            <span className="field-value">{formatNumber(current)}</span>
          </label>
        );
      })}
    </>
  );
}

/** Renders the aggregated membership curve and the crisp value of one output. */
function OutputShape({
  universe,
  aggregated,
  crisp,
  label,
}: {
  universe: number[];
  aggregated: number[];
  crisp: number | null;
  label: string;
}) {
  const low = universe[0];
  const high = universe[universe.length - 1];
  return (
    <>
    <svg
      viewBox="0 0 400 100"
      preserveAspectRatio="none"
      style={{ width: "100%", height: 110 }}
      role="img"
      aria-label={label}
    >
      <polygon
        points={areaPoints(universe, aggregated)}
        fill="var(--series-1)"
        fillOpacity={AREA_OPACITY}
        stroke="var(--series-1)"
        vectorEffect="non-scaling-stroke"
      />
      {crisp !== null && (
        <line
          x1={valueToX(crisp, low, high)}
          x2={valueToX(crisp, low, high)}
          y1={PLOT_TOP}
          y2={PLOT_BOTTOM}
          stroke="var(--series-2)"
          strokeWidth={CRISP_LINE_WIDTH}
          vectorEffect="non-scaling-stroke"
        />
      )}
    </svg>
    <div className="chart-ticks">
      <span>{formatNumber(low)}</span>
      <span>{formatNumber(high)}</span>
    </div>
    </>
  );
}

/** Sentence naming the rules that contributed most to the current outputs. */
function WhyLine({ dominant, t }: { dominant: string[]; t: Translate }) {
  return <p>{t("fuzzy.why", { rules: dominant.join(", ") })}</p>;
}

/** One list item per rule, showing how strongly each rule fired. */
function FiringList({ firing, t }: { firing: Record<string, number>; t: Translate }) {
  const ruleIds = Object.keys(firing);
  return (
    <>
      <h4>{t("fuzzy.firing")}</h4>
      <ul className="firing-list">
        {ruleIds.map((ruleId) => (
          <li key={ruleId}>
            <span className="rule-id">{ruleId}</span>
            <progress max={1} value={firing[ruleId]} aria-label={ruleId} />
            <span className="rule-percent">{Math.round(firing[ruleId] * PERCENT)}%</span>
          </li>
        ))}
      </ul>
    </>
  );
}

/** Renders the crisp value of one output, or a note when no rule covered it. */
function OutputValue({ crisp, unit, t }: { crisp: number | null; unit?: string; t: Translate }) {
  if (crisp === null) {
    return <p className="status">{t("fuzzy.output.none")}</p>;
  }
  return (
    <p className="crisp-value">
      {formatNumber(crisp)}
      {unit ? ` ${unit}` : ""}
    </p>
  );
}

/**
 * What-if panel: sliders for every input, then the inferred outputs.
 *
 * When `inference` is null only the sliders are rendered, because there is
 * nothing to show yet.
 */
export function InferencePanel({
  document,
  values,
  onValues,
  inference,
  t,
}: {
  document: FuzzyDocument;
  values: Record<string, number>;
  onValues: (next: Record<string, number>) => void;
  inference: FuzzyInference | null;
  t: Translate;
}) {
  return (
    <div className="inference-panel">
      <h3>{t("fuzzy.whatif")}</h3>
      <p className="hint">{t("fuzzy.whatif.hint")}</p>
      <InputSliders document={document} values={values} onValues={onValues} />
      {inference !== null && (
        <>
          {document.outputs.map((output) => {
            const shape = inference.outputs[output.id];
            return (
              <section className="fuzzy-output" key={output.id}>
                <h4>{`${t("fuzzy.output")}: ${variableName(output)}`}</h4>
                <OutputValue crisp={shape.crisp} unit={output.unit} t={t} />
                <OutputShape
                  universe={shape.universe}
                  aggregated={shape.aggregated}
                  crisp={shape.crisp}
                  label={output.id}
                />
              </section>
            );
          })}
          {inference.dominant.length > 0 && <WhyLine dominant={inference.dominant} t={t} />}
          <FiringList firing={inference.firing} t={t} />
        </>
      )}
    </div>
  );
}

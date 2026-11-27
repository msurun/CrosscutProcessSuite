// Render one editable FOPDT path at every input/CV intersection.
// The parent values and fit verdict remain visible while the engineer edits a copy.
import type { Translate } from "../findings";
import { fopdtStep } from "../fopdtStep";
import type { IdentModelVersion, ModelPair } from "../mpcModelApi";

export type PairDraft = Omit<ModelPair, "gain" | "time_constant_s" | "dead_time_s"> & {
  gain: string; time_constant_s: string; dead_time_s: string;
};
const PARAMETER_FIELDS = ["gain", "time_constant_s", "dead_time_s"] as const;
const PLOT_SAMPLES = 61; // Uniform samples including both endpoints.
const SETTLING_CONSTANTS = 5; // Five time constants reach 99.3 % of the final value.
const PLOT_WIDTH = 180;
const PLOT_HEIGHT = 72;
const PLOT_PADDING = 6;

/** Copy parameter text so a temporarily blank input is never silently treated as zero. */
export function draftModelPairs(model: IdentModelVersion): PairDraft[] {
  return model.pairs.map((pair) => ({ ...pair, gain: String(pair.gain),
    time_constant_s: String(pair.time_constant_s), dead_time_s: String(pair.dead_time_s) }));
}

/** A draft must represent finite FOPDT parameters: tau > 0 and delay >= 0 seconds. */
export function isValidPair(pair: PairDraft): boolean {
  return PARAMETER_FIELDS.every((field) => pair[field].trim() !== "" && Number.isFinite(Number(pair[field])))
    && Number(pair.time_constant_s) > 0 && Number(pair.dead_time_s) >= 0;
}

/** Convert engineering values into SVG coordinates with zero and signed final gain in view. */
function stepPoints(parameters: Parameters<typeof fopdtStep>[0], horizonS: number): string {
  const minimum = Math.min(0, parameters.gain), range = Math.abs(parameters.gain) || 1;
  // Samples are [time seconds, CV deviation]; SVG y runs downward, opposite to CV value.
  return Array.from({ length: PLOT_SAMPLES }, (_, index) => {
    const fraction = index / (PLOT_SAMPLES - 1);
    const response = fopdtStep(parameters, fraction * horizonS);
    return `${PLOT_PADDING + fraction * (PLOT_WIDTH - 2 * PLOT_PADDING)},${PLOT_HEIGHT - PLOT_PADDING - (response - minimum) / range * (PLOT_HEIGHT - 2 * PLOT_PADDING)}`;
  }).join(" ");
}

/** Draw a unit-input step in CV units; disabled paths have zero effective response. */
function StepPlot({ pair, t }: { pair: PairDraft; t: Translate }) {
  if (!isValidPair(pair)) return null;
  const parameters = { gain: pair.enabled ? Number(pair.gain) : 0,
    timeConstantS: Number(pair.time_constant_s), deadTimeS: Number(pair.dead_time_s) };
  const horizonS = parameters.deadTimeS + SETTLING_CONSTANTS * parameters.timeConstantS;
  if (!Number.isFinite(horizonS)) return null;
  return <svg role="img" aria-label={t("modelMatrix.plot", { pair: pairName(pair) })}
    viewBox={`0 0 ${PLOT_WIDTH} ${PLOT_HEIGHT}`} width={PLOT_WIDTH} height={PLOT_HEIGHT}>
    <polyline fill="none" stroke="currentColor" strokeWidth="2" points={stepPoints(parameters, horizonS)} />
    <title>{t("modelMatrix.plotRange", { seconds: horizonS.toPrecision(3) })}</title>
  </svg>;
}

/** A readable path name also makes every matrix input's accessible label unique. */
function pairName(pair: Pick<ModelPair, "input_name" | "cv_name">): string {
  return `${pair.input_name} → ${pair.cv_name}`;
}

/** Show the exact original parameter next to every changed value. */
function PairDifference({ pair, parent, t }: { pair: PairDraft; parent: ModelPair; t: Translate }) {
  const changes = PARAMETER_FIELDS.filter((field) => Number(pair[field]) !== parent[field]);
  return <ul aria-label={t("modelMatrix.diff", { pair: pairName(pair) })}>
    {changes.map((field) => <li key={field}>{t(`modelMatrix.${field}`)}: {t("modelMatrix.change", { old: parent[field], new: pair[field] })}</li>)}
    {pair.enabled !== parent.enabled && <li>{t("modelMatrix.enabled")}: {t("modelMatrix.change", {
      old: t(parent.enabled ? "modelMatrix.on" : "modelMatrix.off"),
      new: t(pair.enabled ? "modelMatrix.on" : "modelMatrix.off"),
    })}</li>}
    {changes.length === 0 && pair.enabled === parent.enabled && <li>{t("modelMatrix.unchanged")}</li>}
  </ul>;
}

/** Edit one path without overwriting its identification quality evidence. */
function PairCell({ pair, parent, onChange, t }: {
  pair: PairDraft; parent: ModelPair; onChange: (next: PairDraft) => void; t: Translate;
}) {
  return <td><p>{t(pair.quality.passed ? "modelMatrix.passed" : "modelMatrix.failed")}</p>
    <p>{pair.quality.reasons.join("; ")}</p>
    <label>{t("modelMatrix.enabled")} {pairName(pair)}<input type="checkbox" checked={pair.enabled}
      onChange={(event) => onChange({ ...pair, enabled: event.target.checked })} /></label>
    {PARAMETER_FIELDS.map((field) => <label key={field} style={{ display: "block" }}>
      {t(`modelMatrix.${field}`)} {pairName(pair)}
      <input type="number" step="any" required value={pair[field]}
        min={field === "dead_time_s" ? 0 : undefined}
        onChange={(event) => onChange({ ...pair, [field]: event.target.value })} />
    </label>)}
    <PairDifference pair={pair} parent={parent} t={t} /><StepPlot pair={pair} t={t} />
  </td>;
}

/** Arrange rows by MV/DV input and columns by measured CV, keeping model order. */
export function ModelMatrixGrid({ parent, pairs, onChange, t }: {
  parent: IdentModelVersion; pairs: PairDraft[]; onChange: (pairs: PairDraft[]) => void; t: Translate;
}) {
  return <div style={{ overflowX: "auto" }}><table aria-label={t("modelMatrix.grid")}>
    <thead><tr><th scope="col">{t("modelMatrix.input")}</th>
      {parent.cv_names.map((name) => <th scope="col" key={name}>{name}</th>)}</tr></thead>
    <tbody>{parent.input_names.map((name) => <tr key={name}><th scope="row">{name}</th>
      {parent.cv_names.map((cv) => {
        const index = pairs.findIndex((pair) => pair.input_name === name && pair.cv_name === cv);
        return <PairCell key={cv} pair={pairs[index]} parent={parent.pairs[index]} t={t}
          onChange={(next) => onChange(pairs.map((pair, pairIndex) => pairIndex === index ? next : pair))} />;
      })}</tr>)}</tbody>
  </table></div>;
}

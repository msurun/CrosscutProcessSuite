// Display MPC and PID trajectories against their shared engineering constraints.
// Each variable has its own scale so unrelated engineering units are never overlaid.
import type { Translate } from "../findings";
import type { SimulationResult, SimulationTrace } from "../mpcSimulatorApi";

const WIDTH = 640; // SVG view-box units.
const HEIGHT = 180;
const MARGIN = 28;
const COLORS = { mpc: "#17689d", pid: "#a44618", constraint: "#646464", target: "#347339" };
interface ChartData {
  name: string; bounds: number[]; target: number[]; range: [number, number]; time: number[];
  lines: { values: number[]; color: string }[];
}

/** Map engineering values to view-box coordinates, keeping the limits in the visible range. */
function coordinates(values: number[], range: [number, number]): string {
  const [lower, upper] = range;
  return values.map((value, index) => `${MARGIN + index * (WIDTH - 2 * MARGIN) / Math.max(1, values.length - 1)},${
    HEIGHT - MARGIN - (value - lower) * (HEIGHT - 2 * MARGIN) / (upper - lower)}`).join(" ");
}

/** Plot one variable with accessible text, a legend and shared bounds for both controllers. */
function variableData(result: SimulationResult, kind: "cv" | "mv", index: number): ChartData {
  const key = kind === "cv" ? "cvs" : "mvs";
  const mpc = result.mpc[key].map((row) => row[index]);
  const pid = result.pid[key].map((row) => row[index]);
  const bounds = [result.limits[`${kind}_lower`][index], result.limits[`${kind}_upper`][index]];
  const target = kind === "cv" ? result.targets.map((row) => row[index]) : [];
  const lower = Math.min(...mpc, ...pid, ...bounds, ...target);
  const upper = Math.max(...mpc, ...pid, ...bounds, ...target);
  const name = (kind === "cv" ? result.cv_names : result.mv_names)?.[index] ?? `${kind.toUpperCase()} ${index + 1}`;
  const lines = [{ values: mpc, color: COLORS.mpc }, { values: pid, color: COLORS.pid },
    ...bounds.map((value) => ({ values: result.time_s.map(() => value), color: COLORS.constraint }))];
  return { name, bounds, target, range: [lower, upper === lower ? lower + 1 : upper], lines, time: result.time_s };
}

/** Draw one trajectory with matching scales for MPC, PID, targets and limits. */
function VariableChart({ data, t }: { data: ChartData; t: Translate }) {
  const { name, bounds, range, lines, target, time } = data;
  return <figure><figcaption>{name} — {t("precommission.legend")} ({bounds.join(" … ")})</figcaption>
    <svg role="img" aria-label={t("precommission.chart", { name })} viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      style={{ width: "100%", maxWidth: WIDTH }}>
      {lines.map((line, position) => <polyline key={position} fill="none" stroke={line.color}
        strokeWidth="2" strokeDasharray={position > 0 ? "6 4" : undefined} points={coordinates(line.values, range)} />)}
      {target.length > 0 && <polyline fill="none" stroke={COLORS.target} strokeDasharray="2 3" points={coordinates(target, range)} />}
      <text x="0" y="16">{range[1].toPrecision(3)}</text><text x="0" y={HEIGHT - MARGIN}>{range[0].toPrecision(3)}</text>
      <text x={MARGIN} y={HEIGHT - 3}>0</text>
      <text x={WIDTH / 2} y={HEIGHT - 3}>{t("precommission.time")}</text>
      <text x={WIDTH - 60} y={HEIGHT - 3}>{time[time.length - 1]}</text>
    </svg>
  </figure>;
}

/** Keep each KPI's variable ordering explicit; a null settling time means never settled. */
function metricRows(trace: SimulationTrace): Record<string, (number | null)[]> {
  const { constraint_violations, ...metrics } = trace.kpis;
  return { ...metrics, ...Object.fromEntries(Object.entries(constraint_violations)
    .map(([key, values]) => [`violations_${key}`, values])) };
}

/** Keep each KPI's variable ordering explicit; a null settling time means never settled. */
function KpiTable({ result, t }: { result: SimulationResult; t: Translate }) {
  const values = (row: (number | null)[]) => row.map((value) =>
    value === null ? t("precommission.unsettled") : Number(value.toPrecision(5)).toString()).join(", ");
  return <table><caption>{t("precommission.kpis")}</caption>
    <thead><tr><th scope="col">{t("precommission.metric")}</th><th scope="col">MPC</th><th scope="col">PID</th></tr></thead>
    <tbody>{Object.entries(metricRows(result.mpc)).map(([key, row]) => <tr key={key}>
      <th scope="row">{t(`precommission.${key}`)}</th><td>{values(row)}</td><td>{values(metricRows(result.pid)[key])}</td>
    </tr>)}</tbody>
  </table>;
}

/** Render every CV and MV, followed by the comparison's per-variable KPI table. */
export function PrecommissionResults({ result, t }: { result: SimulationResult; t: Translate }) {
  return <div>
    {result.limits.cv_lower.map((_, index) => <VariableChart key={`cv${index}`} data={variableData(result, "cv", index)} t={t} />)}
    {result.limits.mv_lower.map((_, index) => <VariableChart key={`mv${index}`} data={variableData(result, "mv", index)} t={t} />)}
    <KpiTable result={result} t={t} />
  </div>;
}

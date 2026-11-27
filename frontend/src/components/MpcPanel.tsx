// frontend/src/components/MpcPanel.tsx
/**
 * MPC part of the controller detail: why the controller did or did not move, the MV table with
 * limits and per-cycle reason codes, the CV table with limits, targets and relaxed flags, the
 * predicted CV trajectories and the active constraints. Read-only: the controller only proposes,
 * the gateway decides (ADR 011, 016).
 */

import type { MpcConstraint, MpcCv, MpcDiagnostics, MpcMv } from "../controllersApi";
import type { Translate } from "../findings";

const WIDTH = 240;
const HEIGHT = 72;
const PAD = 6;
const STROKE = { line: "var(--series-1, #17689d)", limit: "currentColor", target: "var(--series-2, #347339)" };

/** Compact number text: 4 significant digits, no trailing zeros. */
export function num(value: number): string {
  return String(Number(value.toPrecision(4)));
}

function y(value: number, lo: number, hi: number): number {
  return HEIGHT - PAD - ((value - lo) * (HEIGHT - 2 * PAD)) / (hi - lo);
}

/** Predicted trajectory of one CV between its limits (dashed) and its target (dotted). */
function Trajectory({ cv, t }: { cv: MpcCv; t: Translate }) {
  const marks = [cv.lo, cv.hi, ...(cv.target === null ? [] : [cv.target]), ...cv.predicted];
  const lo = Math.min(...marks);
  const hi = Math.max(...marks) === lo ? lo + 1 : Math.max(...marks);
  const last = cv.predicted.length - 1;
  const step = (WIDTH - 2 * PAD) / Math.max(1, last);
  const points = cv.predicted.map((v, i) => `${PAD + i * step},${y(v, lo, hi)}`).join(" ");
  const flat = (v: number) => ({ x1: PAD, x2: WIDTH - PAD, y1: y(v, lo, hi), y2: y(v, lo, hi) });
  const end = last >= 0 ? num(cv.predicted[last]) : "-";
  return (
    <svg
      role="img" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} style={{ width: "100%", maxWidth: WIDTH }}
      aria-label={t("controllers.mpc.chart", { id: cv.id, now: num(cv.value), end })}
      data-testid={`mpc-chart-${cv.id}`}
    >
      <line {...flat(cv.lo)} stroke={STROKE.limit} strokeDasharray="4 3" />
      <line {...flat(cv.hi)} stroke={STROKE.limit} strokeDasharray="4 3" />
      {cv.target !== null && <line {...flat(cv.target)} stroke={STROKE.target} strokeDasharray="1 3" />}
      {cv.predicted.length > 0 && <polyline fill="none" stroke={STROKE.line} strokeWidth="2" points={points} />}
    </svg>
  );
}

function MvTable({ mvs, t }: { mvs: MpcMv[]; t: Translate }) {
  return (
    <div className="table-scroll" tabIndex={0} role="region" aria-label={t("controllers.mpc.mvs")}>
      <table className="loops-table" data-testid="mpc-mvs">
        <caption className="hint">{t("controllers.mpc.mvs")}</caption>
        <thead>
          <tr>
            <th scope="col">{t("controllers.col.variable")}</th>
            <th scope="col">{t("controllers.mpc.col.sp")}</th>
            <th scope="col">{t("controllers.mpc.col.proposed")}</th>
            <th scope="col">{t("controllers.mpc.col.limits")}</th>
            <th scope="col">{t("controllers.mpc.col.code")}</th>
          </tr>
        </thead>
        <tbody>
          {mvs.map((mv) => (
            <tr key={mv.id} data-testid={`mpc-mv-${mv.id}`}>
              <th scope="row">{mv.id}</th>
              <td>{num(mv.sp)}</td>
              <td>{num(mv.proposed)}</td>
              <td>{num(mv.lo)} .. {num(mv.hi)}</td>
              <td>{t(`controllers.mpc.code.${mv.code}`)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CvTable({ cvs, t }: { cvs: MpcCv[]; t: Translate }) {
  return (
    <div className="table-scroll" tabIndex={0} role="region" aria-label={t("controllers.mpc.cvs")}>
      <table className="loops-table" data-testid="mpc-cvs">
        <caption className="hint">{t("controllers.mpc.cvs")}</caption>
        <thead>
          <tr>
            <th scope="col">{t("controllers.col.variable")}</th>
            <th scope="col">{t("controllers.col.value")}</th>
            <th scope="col">{t("controllers.mpc.col.target")}</th>
            <th scope="col">{t("controllers.mpc.col.limits")}</th>
            <th scope="col">{t("controllers.mpc.col.relaxed")}</th>
            <th scope="col">{t("controllers.mpc.col.prediction")}</th>
          </tr>
        </thead>
        <tbody>
          {cvs.map((cv) => (
            <tr key={cv.id} data-testid={`mpc-cv-${cv.id}`}>
              <th scope="row">{cv.id}</th>
              <td>{num(cv.value)}</td>
              <td>{cv.target === null ? t("controllers.none") : num(cv.target)}</td>
              <td>{num(cv.lo)} .. {num(cv.hi)}</td>
              <td>{cv.relaxed ? t("controllers.mpc.relaxed") : t("controllers.none")}</td>
              <td><Trajectory cv={cv} t={t} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Constraints({ items, t }: { items: MpcConstraint[]; t: Translate }) {
  if (items.length === 0) return <p className="hint" data-testid="mpc-constraints">{t("controllers.mpc.noConstraints")}</p>;
  return (
    <ul data-testid="mpc-constraints" aria-label={t("controllers.mpc.constraints")}>
      {items.map((c) => (
        <li key={`${c.kind}-${c.variable}-${c.side}-${c.sample}`}>
          {t(`controllers.mpc.constraint.${c.side}`, { kind: c.kind, variable: c.variable, sample: c.sample })}
        </li>
      ))}
    </ul>
  );
}

export function MpcPanel({ diagnostics, t }: { diagnostics: MpcDiagnostics; t: Translate }) {
  const why = diagnostics.why_no_move;
  return (
    <section data-testid="mpc-panel" aria-labelledby="mpc-title">
      <h3 id="mpc-title">{t("controllers.mpc.title")}</h3>
      <p data-testid="mpc-why">
        <strong>
          {why === null ? t("controllers.mpc.moving") : t("controllers.mpc.whyNoMove", { reason: t(`controllers.mpc.code.${why}`) })}
        </strong>
        {diagnostics.reason && <span className="hint"> ({diagnostics.reason})</span>}
      </p>
      <p className="hint">{t("controllers.mpc.shedRule", { n: diagnostics.shed_after })}</p>
      <MvTable mvs={diagnostics.mvs} t={t} />
      <CvTable cvs={diagnostics.cvs} t={t} />
      <h4>{t("controllers.mpc.constraints")}</h4>
      <Constraints items={diagnostics.active_constraints} t={t} />
    </section>
  );
}

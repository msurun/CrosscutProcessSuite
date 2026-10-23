// Result panel of the step-test check in the Import view: the verdict (icon and word), the measured
// numbers, the findings with what to do, the tuning wizard's dry run, the chart and the assumptions
// the reader made. The finding texts come from the server (English).
import type { IntakeCheck, IntakeDryRun, IntakeFinding } from "../api";
import type { Translate } from "../findings";
import { formatFixed, formatPercent, formatSignificant } from "../format";
import { verdictLevel } from "../intake";
import { ImportChart } from "./ImportChart";
import { StatusChip } from "./StatusChip";

const SECONDS_PER_MINUTE = 60;

/** Seconds as minutes with one decimal, or a dash for a missing value. */
function minutes(seconds: number | null): string {
  return seconds === null ? "-" : `${formatFixed(seconds / SECONDS_PER_MINUTE, 1)} min`;
}

/** The measured numbers as a definition list. */
function Numbers({ check, t }: { check: IntakeCheck; t: Translate }) {
  const rows: [string, string][] = [
    [t("import.num.samples"), String(check.n)],
    [t("import.num.period"), `${formatFixed(check.dt_median_s, 1)} s`],
    [t("import.num.length"), minutes(check.duration_s)],
    [t("import.num.lead"), check.lead_share === null ? "-" : formatPercent(check.lead_share * 100, 1)],
    [t("import.num.post"), minutes(check.post_last_move_s)],
    [t("import.num.moves"), String(check.n_out_moves)],
    [t("import.num.pvRange"), formatSignificant(check.pv_range, 3)],
    [t("import.num.outRange"), formatSignificant(check.out_range, 3)],
  ];
  return (
    <dl className="advisory-config import-numbers">
      {rows.map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}
    </dl>
  );
}

/** The findings, blocking ones marked, each with what to do. */
function Findings({ findings, t }: { findings: IntakeFinding[]; t: Translate }) {
  if (findings.length === 0) return <p>{t("import.findings.none")}</p>;
  return (
    <ul className="import-findings">
      {findings.map((finding) => (
        <li key={finding.code}>
          <strong>{finding.text}</strong>
          {finding.blocking && <span className="badge badge-partial">{t("import.findings.blocking")}</span>}
          <br />
          <span>{t("import.findings.todo", { text: finding.what_to_do })}</span>
        </li>
      ))}
    </ul>
  );
}

/** What the wizard will say: slope, dead time with its range, the upper-bound rule and R2. */
function DryRun({ run, t }: { run: IntakeDryRun; t: Translate }) {
  const ok = run.verdict === "ok" && run.slope_per_s !== null;
  return (
    <section aria-label={t("import.dry.title")}>
      <h4>{t("import.dry.title")}</h4>
      {!ok && (
        <ul>{[...run.reasons, ...(run.error ? [run.error] : [])].map((reason) => <li key={reason}>{reason}</li>)}</ul>
      )}
      {ok && (
        <dl className="advisory-config import-numbers">
          <div><dt>{t("import.dry.slope")}</dt><dd>{formatSignificant(run.slope_per_s ?? 0, 3)}</dd></div>
          {run.delay_s !== null && run.delay_lower_s !== null && run.delay_upper_s !== null && (
            <div>
              <dt>{t("import.dry.delay")}</dt>
              <dd>{t("import.dry.delayValue", { delay: formatFixed(run.delay_s, 0), lower: formatFixed(run.delay_lower_s, 0), upper: formatFixed(run.delay_upper_s, 0) })}</dd>
            </div>
          )}
          {run.r_squared !== null && <div><dt>{t("import.dry.r2")}</dt><dd>{formatFixed(run.r_squared, 3)}</dd></div>}
        </dl>
      )}
      {ok && <p className="hint">{t("import.dry.upper")}</p>}
    </section>
  );
}

/** Verdict, numbers, findings, dry run, chart and assumptions of one check. */
export function ImportCheck({ check, t }: { check: IntakeCheck; t: Translate }) {
  return (
    <section aria-label={t("import.result")} data-testid="import-result">
      <h3>{t("import.result")}</h3>
      <p><StatusChip level={verdictLevel(check.verdict)} label={t(`import.verdict.${check.verdict}`)} /></p>
      <Numbers check={check} t={t} />
      <h4>{t("import.findings.title")}</h4>
      <Findings findings={check.findings} t={t} />
      {check.dry_run !== null && <DryRun run={check.dry_run} t={t} />}
      <ImportChart check={check} t={t} />
      <h4>{t("import.readAs")}</h4>
      <ul>{check.read_as.map((note) => <li key={note}>{note}</li>)}</ul>
    </section>
  );
}

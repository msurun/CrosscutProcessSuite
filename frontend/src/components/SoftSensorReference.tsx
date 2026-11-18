// Reference inputs of a soft sensor run: for every reference measurement (analyser, inferential) its
// window settings, mean coverage, share of valid windows, the latest window, and the check of the lab
// bias correction (RMSE of the reference against the lab values without and with the EWMA correction).
import type { ReferenceReport } from "../api";
import type { Translate } from "../findings";
import { formatFixed, formatSignificant } from "../format";

const PERCENT = 100;
const PERCENT_DECIMALS = 1;
const MISSING = "--";

const percent = (share: number | null): string => (share === null ? MISSING : `${formatFixed(share * PERCENT, PERCENT_DECIMALS)} %`);
const rmse = (value: number | null): string => (value === null ? MISSING : formatSignificant(value));

/** Text and test id of the verdict on the correction. */
function verdict(helps: boolean | null, t: Translate): string {
  if (helps === null) return t("soft.ref.unknown");
  return helps ? t("soft.ref.helps") : t("soft.ref.hurts");
}

/** The latest window as text: valid or not, with its coverage. */
function latest(row: ReferenceReport, t: Translate): string {
  const coverage = formatFixed((row.latest_coverage ?? 0) * PERCENT, PERCENT_DECIMALS);
  return t(row.latest_valid ? "soft.ref.latestValid" : "soft.ref.latestInvalid", { coverage });
}

/** One table row per reference input. */
function ReferenceRow({ row, t }: { row: ReferenceReport; t: Translate }) {
  return (
    <tr data-testid={`soft-ref-${row.tag}`}>
      <th scope="row">{row.tag}</th>
      <td>{`${row.window_s} s / ${row.shift_s} s`}</td>
      <td>{percent(row.coverage_mean)}</td>
      <td data-testid="soft-ref-valid">{percent(row.valid_share)}</td>
      <td>{latest(row, t)}</td>
      <td>{row.n_pairs}</td>
      <td>{rmse(row.rmse_raw)}</td>
      <td>{rmse(row.rmse_corrected)}</td>
      <td data-testid="soft-ref-verdict">{verdict(row.helps, t)}</td>
    </tr>
  );
}

/** The reference table with its explanations; nothing is shown when no reference input is configured. */
export function SoftSensorReference({ rows, t }: { rows: readonly ReferenceReport[]; t: Translate }) {
  if (rows.length === 0) return null;
  const cols = ["tag", "window", "coverage", "valid", "latest", "pairs", "rmseRaw", "rmseCorrected", "verdict"] as const;
  return (
    <section aria-label={t("soft.ref.title")} data-testid="soft-reference">
      <h3>{t("soft.ref.title")}</h3>
      <p className="hint">{t("soft.ref.hint")}</p>
      <div className="table-scroll" tabIndex={0} role="region" aria-label={t("soft.ref.caption")}>
        <table className="loops-table">
          <caption>{t("soft.ref.caption")}</caption>
          <thead>
            <tr>{cols.map((c) => <th key={c} scope="col">{t(`soft.ref.col.${c}`)}</th>)}</tr>
          </thead>
          <tbody>{rows.map((row) => <ReferenceRow key={row.tag} row={row} t={t} />)}</tbody>
        </table>
      </div>
      <p className="hint">{t("soft.ref.biasHint")}</p>
    </section>
  );
}

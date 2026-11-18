// Backup mode of a soft sensor run: a status chip (measured or substituted by the virtual sensor),
// the quality code and reason of the latest row, the number of substituted rows and the history of
// every switch (time, direction, reason). Nothing is shown when backup mode is not configured.
import type { SoftSensorBackup as BackupResult, BackupSwitch } from "../api";
import type { Translate } from "../findings";
import { formatFixed } from "../format";

const SECONDS_PER_HOUR = 3600;
const HOUR_DECIMALS = 2;
const QUALITY_KEYS = ["soft.backup.quality.0", "soft.backup.quality.1", "soft.backup.quality.2"] as const;

const hours = (seconds: number): string => `${formatFixed(seconds / SECONDS_PER_HOUR, HOUR_DECIMALS)} h`;
const reasonText = (reason: string, t: Translate): string => (reason === "" ? "--" : t(`soft.backup.reason.${reason}`));

/** The chip with the source of the latest output value. */
function StatusChip({ backup, t }: { backup: BackupResult; t: Translate }) {
  const substituted = backup.latest.substituted;
  const className = substituted ? "status-chip status-chip--warning" : "status-chip status-chip--ok";
  return (
    <p>
      <span className={className} data-testid="soft-backup-status">
        {t(substituted ? "soft.backup.statusBackup" : "soft.backup.statusMeasured", { tag: backup.measured_tag })}
      </span>
      {" "}
      <span data-testid="soft-backup-quality">
        {t("soft.backup.qualityLine", { code: backup.latest.quality, text: t(QUALITY_KEYS[backup.latest.quality] ?? QUALITY_KEYS[2]), reason: reasonText(backup.latest.reason, t) })}
      </span>
    </p>
  );
}

/** One row of the switch history. */
function SwitchRow({ row, t }: { row: BackupSwitch; t: Translate }) {
  return (
    <tr>
      <td>{hours(row.t_s)}</td>
      <td>{t(`soft.backup.state.${row.from}`)}</td>
      <td>{t(`soft.backup.state.${row.to}`)}</td>
      <td>{reasonText(row.reason, t)}</td>
    </tr>
  );
}

/** The backup status and the switch history table. */
export function SoftSensorBackup({ backup, t }: { backup: BackupResult | null; t: Translate }) {
  if (backup === null) return null;
  const cols = ["time", "from", "to", "reason"] as const;
  return (
    <section aria-label={t("soft.backup.title")} data-testid="soft-backup">
      <h3>{t("soft.backup.title")}</h3>
      <p className="hint">{t("soft.backup.hint")}</p>
      <StatusChip backup={backup} t={t} />
      <p data-testid="soft-backup-count">{t("soft.backup.count", { n: backup.n_substituted })}</p>
      {backup.switches.length === 0 ? (
        <p className="hint" data-testid="soft-backup-none">{t("soft.backup.noSwitches")}</p>
      ) : (
        <div className="table-scroll" tabIndex={0} role="region" aria-label={t("soft.backup.caption")}>
          <table className="loops-table" data-testid="soft-backup-switches">
            <caption>{t("soft.backup.caption")}</caption>
            <thead>
              <tr>{cols.map((c) => <th key={c} scope="col">{t(`soft.backup.col.${c}`)}</th>)}</tr>
            </thead>
            <tbody>{backup.switches.map((row) => <SwitchRow key={`${row.t_s}-${row.to}`} row={row} t={t} />)}</tbody>
          </table>
        </div>
      )}
    </section>
  );
}

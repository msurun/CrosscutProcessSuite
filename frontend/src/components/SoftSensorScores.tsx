// Summary numbers of a soft sensor run: the RMSE of the estimate, of the bias-corrected estimate and
// of the carry-forward baseline (the last lab value available) against the lab values at the lab
// times, for all lab points of the run and for the part after the train end (not used in fitting);
// and the drift episodes with the limit that raises the flag.
import type { DriftEpisode, SoftSensorModelSummary } from "../api";
import type { Translate } from "../findings";
import { formatFixed, formatSignificant } from "../format";
import { toHours } from "../anomaly";
import type { LabScore } from "../softsensorSeries";

const HOUR_DECIMALS = 2;
const MISSING = "--";
const DRIFT_SIGMAS = 2;

const rmseText = (value: number | null): string => (value === null ? MISSING : formatSignificant(value));

interface ScoresProps {
  all: LabScore;
  afterCut: LabScore;
  nLabUsed: number;
  t: Translate;
}

/** One row of the score table. */
function ScoreRow({ label, score }: { label: string; score: LabScore }) {
  return (
    <tr>
      <th scope="row">{label}</th>
      <td>{score.n}</td>
      <td>{rmseText(score.estimate)}</td>
      <td>{rmseText(score.corrected)}</td>
      <td>{rmseText(score.baseline)}</td>
    </tr>
  );
}

/** The RMSE table; the first row also uses lab points the model was fitted on. */
export function SoftSensorScores({ all, afterCut, nLabUsed, t }: ScoresProps) {
  return (
    <section aria-label={t("soft.score.title")} data-testid="soft-scores">
      <h3>{t("soft.score.title")}</h3>
      <div className="table-scroll" tabIndex={0} role="region" aria-label={t("soft.score.caption")}>
        <table className="loops-table">
          <caption>{t("soft.score.caption")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("soft.score.col.points")}</th>
              <th scope="col">{t("soft.score.col.n")}</th>
              <th scope="col">{t("soft.score.col.estimate")}</th>
              <th scope="col">{t("soft.score.col.corrected")}</th>
              <th scope="col">{t("soft.score.col.baseline")}</th>
            </tr>
          </thead>
          <tbody>
            <ScoreRow label={t("soft.score.all")} score={all} />
            <ScoreRow label={t("soft.score.afterCut")} score={afterCut} />
          </tbody>
        </table>
      </div>
      <p className="hint">{t("soft.score.hint")}</p>
      <p className="hint">{t("soft.score.labUsed", { n: nLabUsed })}</p>
    </section>
  );
}

interface DriftProps {
  episodes: readonly DriftEpisode[];
  model: SoftSensorModelSummary;
  t: Translate;
}

/** The drift episodes (or "none") and the limit that raises the flag. */
export function SoftSensorDrift({ episodes, model, t }: DriftProps) {
  const limit = model.cv_sigma === null ? MISSING : formatSignificant(DRIFT_SIGMAS * model.cv_sigma);
  const hours = (seconds: number) => formatFixed(toHours(seconds), HOUR_DECIMALS);
  return (
    <section aria-label={t("soft.drift.title")} data-testid="soft-drift">
      <h3>
        {t("soft.drift.title")} <span className="badge badge-partial" data-testid="soft-drift-badge">{t("soft.drift.badge")}</span>
      </h3>
      <p className="notice" role="note">{t("soft.drift.notValidated")}</p>
      <p className="hint">{t("soft.drift.rule", { limit })}</p>
      {episodes.length === 0 ? (
        <p className="status">{t("soft.drift.none")}</p>
      ) : (
        <div className="table-scroll" tabIndex={0} role="region" aria-label={t("soft.drift.title")}>
          <table className="loops-table">
            <caption>{t("soft.drift.count", { count: episodes.length })}</caption>
            <thead>
              <tr>
                <th scope="col">{t("soft.drift.col.start")}</th>
                <th scope="col">{t("soft.drift.col.end")}</th>
              </tr>
            </thead>
            <tbody>
              {episodes.map((episode) => (
                <tr key={episode.start_s}>
                  <td>{hours(episode.start_s)}</td>
                  <td>{hours(episode.end_s)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

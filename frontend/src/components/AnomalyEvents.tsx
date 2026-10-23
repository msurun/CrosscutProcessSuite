// Events table of a scan: start, end, duration, peak of T2 and SPE as a multiple of the limit,
// which statistic exceeded and whether the event is closed. The button of a row selects the
// event whose tag contributions are shown below the table.
import type { AnomalyEvent } from "../api";
import type { Translate } from "../findings";
import { formatFixed } from "../format";
import { eventRows, toHours } from "../anomaly";

const HOUR_DECIMALS = 2;
const RATIO_DECIMALS = 2;
const SECONDS_PER_MINUTE = 60;
const COLUMNS = ["n", "start", "end", "duration", "t2", "spe", "exceeded", "state"];

interface EventsTableProps {
  events: readonly AnomalyEvent[];
  t2Limit: number;
  speLimit: number;
  selected: number;
  onSelect: (index: number) => void;
  t: Translate;
}

/** The table, or the "no events" message. */
export function AnomalyEventsTable({ events, t2Limit, speLimit, selected, onSelect, t }: EventsTableProps) {
  if (events.length === 0) return <p className="status" role="status">{t("anomaly.events.none")}</p>;
  const rows = eventRows(events, t2Limit, speLimit);
  return (
    <div className="table-scroll">
      <table className="loops-table">
        <caption>{t("anomaly.events.count", { count: rows.length })}</caption>
        <thead>
          <tr>{COLUMNS.map((key) => <th key={key} scope="col">{t(`anomaly.events.col.${key}`)}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.index}>
              <th scope="row">
                <button
                  type="button"
                  className="filter-chip"
                  aria-pressed={row.index === selected}
                  aria-label={t("anomaly.events.select", { n: row.index + 1 })}
                  onClick={() => onSelect(row.index)}
                >
                  {row.index + 1}
                </button>
              </th>
              <td>{formatFixed(toHours(row.startS), HOUR_DECIMALS)}</td>
              <td>{formatFixed(toHours(row.endS), HOUR_DECIMALS)}</td>
              <td>{formatFixed(row.durationS / SECONDS_PER_MINUTE, 0)}</td>
              <td>{formatFixed(row.t2Ratio, RATIO_DECIMALS)}</td>
              <td>{formatFixed(row.speRatio, RATIO_DECIMALS)}</td>
              <td>{t(`anomaly.events.exceeded.${row.exceeded}`)}</td>
              <td>{row.closed ? t("anomaly.events.state.closed") : t("anomaly.events.state.open")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

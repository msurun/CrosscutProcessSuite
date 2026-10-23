// Step 2 of the Plant import view: what the server read from the uploaded files.
// Shows the time span, sampling period and gaps, the detected loops with their missing signals,
// the test windows found in the file and the server's notes. Read-only, the user decides next.
import type { Translate } from "../findings";
import { noteText, type PlantPreview } from "../plantImport";

/** Sample count, local time range, period, gaps and the number of skipped columns, one line each. */
function Summary({ preview, t }: { preview: PlantPreview; t: Translate }) {
  const lines = [
    t("plant.preview.rows", { rows: preview.n_rows, columns: preview.n_columns }),
    t("plant.preview.range", { start: preview.start_local, end: preview.end_local }),
    t("plant.preview.period", { seconds: preview.period_s }),
    preview.n_gaps > 0 ? t("plant.preview.gaps", { count: preview.n_gaps }) : t("plant.preview.noGaps"),
  ];
  if (preview.skipped.count > 0) lines.push(t("plant.preview.skipped", { count: preview.skipped.count }));
  return <ul className="summary-lines">{lines.map((line) => <li key={line}>{line}</li>)}</ul>;
}

/** The loops the server recognised, with the signals each one is still missing. */
function LoopsTable({ preview, t }: { preview: PlantPreview; t: Translate }) {
  return (
    <div className="table-scroll" tabIndex={0} role="region" aria-label={t("plant.loops.title")}>
      <table className="loops-table">
        <caption>{t("plant.loops.title")}</caption>
        <thead>
          <tr>
            <th scope="col">{t("plant.loops.id")}</th>
            <th scope="col">{t("plant.loops.kind")}</th>
            <th scope="col">{t("plant.loops.cell")}</th>
            <th scope="col">{t("plant.loops.status")}</th>
          </tr>
        </thead>
        <tbody>
          {preview.loops.map((loop) => (
            <tr key={loop.id}>
              <td>{loop.name}</td>
              <td>{t(`plant.kind.${loop.process_kind}`)}</td>
              <td>{loop.cell}</td>
              <td>{loop.complete ? t("plant.loops.complete") : t("plant.loops.missing", { roles: loop.missing.join(", ") })}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The stretches of usable data, or a single line saying there are none. */
function WindowsTable({ preview, t }: { preview: PlantPreview; t: Translate }) {
  if (preview.test_windows.length === 0) {
    return <p className="notice">{t("plant.windows.none")}</p>;
  }
  return (
    <div className="table-scroll" tabIndex={0} role="region" aria-label={t("plant.windows.title")}>
      <table className="loops-table">
        <caption>{t("plant.windows.title")}</caption>
        <thead>
          <tr>
            <th scope="col">{t("plant.windows.label")}</th>
            <th scope="col">{t("plant.windows.start")}</th>
            <th scope="col">{t("plant.windows.end")}</th>
            <th scope="col">{t("plant.windows.rows")}</th>
          </tr>
        </thead>
        <tbody>
          {preview.test_windows.map((window) => (
            <tr key={window.label}>
              <td>{window.label}</td>
              <td>{window.start_utc}</td>
              <td>{window.end_utc}</td>
              <td>{window.rows}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The server's explanations, translated when a key exists and verbatim otherwise. */
function NotesList({ preview, t }: { preview: PlantPreview; t: Translate }) {
  return (
    <section aria-label={t("plant.notes.title")}>
      <h4>{t("plant.notes.title")}</h4>
      <ul className="notice">
        {preview.notes.map((note) => <li key={note.code}>{noteText(note, t)}</li>)}
      </ul>
    </section>
  );
}

/** Summary, loop table, test windows and notes for a plant preview. */
export function ImportPlantPreview({ preview, t }: { preview: PlantPreview; t: Translate }) {
  return (
    <section aria-label={t("plant.preview.rows", { rows: preview.n_rows, columns: preview.n_columns })}>
      <h3>{t("plant.preview.rows", { rows: preview.n_rows, columns: preview.n_columns })}</h3>
      <Summary preview={preview} t={t} />
      <LoopsTable preview={preview} t={t} />
      <WindowsTable preview={preview} t={t} />
      <NotesList preview={preview} t={t} />
    </section>
  );
}

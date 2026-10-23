// Import view: bring a step-test CSV from a historian into the application in four steps (choose the
// file, check the preview and mapping, check the record, create a dataset) and open it in the tuning
// wizard. The file is read in the browser; only the new dataset folder is written, nothing reaches a plant.
import type { Translate } from "../findings";
import { mappingComplete } from "../intake";
import { ImportCheck } from "./ImportCheck";
import { ImportCreate, ImportDone } from "./ImportCreate";
import { ImportFile } from "./ImportFile";
import { ImportPreview } from "./ImportPreview";
import { useImport } from "./ImportState";

/** The two persistent notes: nothing is sent to the plant, and how times without a zone are read. */
export function ImportNotes({ t }: { t: Translate }) {
  return (
    <>
      <p className="notice banner-warning" role="note">{t("import.note.local")}</p>
      <p className="notice" role="note">{t("import.note.utc")}</p>
    </>
  );
}

interface PageProps {
  /** Reloads the dataset list of the app. */
  onCreated: () => void;
  /** Opens the tuning view of a loop of a dataset. */
  onOpen: (datasetId: string, loop: string) => void;
  t: Translate;
}

/** The Import view. */
export function ImportPage({ onCreated, onOpen, t }: PageProps) {
  const state = useImport(t, onCreated);
  const { preview, mapping, options, check, created, busy } = state;
  const ready = preview !== null && mapping !== null && options !== null;
  return (
    <section>
      <header className="toolbar"><h2>{t("import.title")}</h2></header>
      <ImportNotes t={t} />
      <ImportFile source={state.source} busy={busy !== null} onFile={state.loadFile} onPasted={state.loadPasted} t={t} />
      {busy === "preview" && <p className="status">{t("trends.loading")}</p>}
      {ready && (
        <>
          <ImportPreview preview={preview} mapping={mapping} options={options} onField={state.setField} onOptions={state.setOptions} t={t} />
          <div className="toolbar">
            <button type="button" disabled={busy !== null || !mappingComplete(mapping, preview.layout)} onClick={state.runCheck}>
              {busy === "check" ? t("import.check.running") : t("import.check.run")}
            </button>
          </div>
        </>
      )}
      {state.error !== null && <p className="status status-error" role="alert">{state.error}</p>}
      {check !== null && <ImportCheck check={check} t={t} />}
      {ready && created === null && <ImportCreate check={check} busy={busy === "create"} onCreate={state.create} t={t} />}
      {created !== null && <ImportDone created={created} onOpen={onOpen} onReset={state.reset} t={t} />}
    </section>
  );
}

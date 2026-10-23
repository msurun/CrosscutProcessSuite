// Plant import view: read a whole plant snapshot in one file, see what the reader found (loops,
// gaps, test windows), choose the time zone and the import scope, then create the dataset.
// The file is read by the backend; only a new dataset folder is written, nothing reaches a plant.
import type { Translate } from "../findings";
import { validDatasetId } from "../plantImport";
import type { PlantImportResult, TzPreset } from "../plantImport";
import { ImportPlantPreview } from "./ImportPlantPreview";
import { usePlantImport } from "./ImportPlantState";

/** The two persistent notes: nothing is sent to the plant, and how local times are read. */
export function ImportPlantNotes({ t }: { t: Translate }) {
  return <p className="notice banner-warning" role="note">{t("plant.note.local")}</p>;
}

interface ZoneProps {
  preset: TzPreset;
  offsetHours: string;
  onPreset: (preset: TzPreset) => void;
  onOffset: (offsetHours: string) => void;
  t: Translate;
}

/** Offsets of the form "UTC+5:30" span more whole hours than a plant snapshot ever needs. */
const MAX_OFFSET_MAGNITUDE_H = 14;

/** The time zone select and, for the offset preset, the number input of the offset in hours. */
function TimeZoneField({ preset, offsetHours, onPreset, onOffset, t }: ZoneProps) {
  return (
    <>
      <div className="field">
        <label className="field-label" htmlFor="plant-tz">{t("plant.tz.label")}</label>
        <select id="plant-tz" className="field-input" value={preset}
          onChange={(event) => onPreset(event.target.value as TzPreset)}>
          <option value="utc">{t("plant.tz.utc")}</option>
          <option value="santiago">{t("plant.tz.santiago")}</option>
          <option value="offset">{t("plant.tz.offset")}</option>
        </select>
      </div>
      {preset === "offset" && (
        <div className="field">
          <label className="field-label" htmlFor="plant-offset">{t("plant.tz.offsetHours")}</label>
          <input id="plant-offset" className="field-input" type="text" inputMode="decimal"
            value={offsetHours} aria-describedby="plant-offset-help" onChange={(e) => onOffset(e.target.value)} />
          <span id="plant-offset-help" className="field-help hint">{t("plant.tz.invalid", { max: MAX_OFFSET_MAGNITUDE_H })}</span>
        </div>
      )}
    </>
  );
}

interface FileProps {
  hasDataFile: boolean;
  onDataFile: (file: File) => void;
  onDictionaryFile: (file: File) => void;
  t: Translate;
}

/** The required data file input and the optional dictionary file input. */
function FileFields({ hasDataFile, onDataFile, onDictionaryFile, t }: FileProps) {
  return (
    <>
      <div className="field">
        <label className="field-label" htmlFor="plant-data">{t("plant.data.label")}</label>
        <input id="plant-data" className="field-input" type="file" accept=".csv,.txt,.tsv,text/csv,text/plain"
          data-chosen={hasDataFile} onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onDataFile(file);
            event.target.value = "";
          }} />
      </div>
      <div className="field">
        <label className="field-label" htmlFor="plant-dictionary">{t("plant.dictionary.label")}</label>
        <input id="plant-dictionary" className="field-input" type="file"
          accept=".csv,.txt,.tsv,text/csv,text/plain" aria-describedby="plant-dictionary-help"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onDictionaryFile(file);
            event.target.value = "";
          }} />
        <span id="plant-dictionary-help" className="field-help hint">{t("plant.dictionary.hint")}</span>
      </div>
    </>
  );
}

interface PreviewButtonProps {
  busy: boolean;
  canPreview: boolean;
  onPreview: () => void;
  t: Translate;
}

/** The button that uploads the files and asks the reader for a preview. */
function PreviewButton({ busy, canPreview, onPreview, t }: PreviewButtonProps) {
  return (
    <div className="toolbar">
      <button type="button" disabled={busy || !canPreview} onClick={onPreview}>
        {busy ? t("plant.preview.running") : t("plant.preview.run")}
      </button>
    </div>
  );
}

interface ImportFormProps {
  scope: "loops" | "process";
  datasetId: string;
  canImport: boolean;
  busyImport: boolean;
  onScope: (scope: "loops" | "process") => void;
  onDatasetId: (datasetId: string) => void;
  onImport: () => void;
  t: Translate;
}

/** The scope and dataset id form; `Import` is enabled when both are valid and nothing is busy. */
function ImportForm({ scope, datasetId, canImport, busyImport, onScope, onDatasetId, onImport, t }: ImportFormProps) {
  const idInvalid = datasetId !== "" && !validDatasetId(datasetId);
  return (
    <div className="knowledge-fields">
      <div className="field">
        <label className="field-label" htmlFor="plant-scope">{t("plant.scope.label")}</label>
        <select id="plant-scope" className="field-input" value={scope}
          onChange={(event) => onScope(event.target.value as "loops" | "process")}>
          <option value="loops">{t("plant.scope.loops")}</option>
          <option value="process">{t("plant.scope.process")}</option>
        </select>
      </div>
      <div className="field">
        <label className="field-label" htmlFor="plant-dataset">{t("plant.dataset.label")}</label>
        <input id="plant-dataset" className="field-input" type="text" value={datasetId} maxLength={64}
          aria-invalid={idInvalid} aria-describedby="plant-dataset-help"
          onChange={(event) => onDatasetId(event.target.value)} />
        <span id="plant-dataset-help" className="field-help hint">{t("plant.dataset.label")}</span>
        {idInvalid && <span role="alert" className="status status-error">{t("plant.dataset.invalid")}</span>}
      </div>
      <div className="toolbar">
        <button type="button" disabled={busyImport || !canImport} onClick={onImport}>
          {busyImport ? t("plant.import.running") : t("plant.import.run")}
        </button>
      </div>
    </div>
  );
}

interface DoneProps {
  result: PlantImportResult;
  onOpen: (datasetId: string, loop: string) => void;
  onReset: () => void;
  t: Translate;
}

/** The success state: what was written, one button per loop into Tuning, and "Start again". */
function ImportPlantDone({ result, onOpen, onReset, t }: DoneProps) {
  return (
    <section aria-label={t("plant.done.title")} data-testid="plant-done">
      <h3>{t("plant.done.title")}</h3>
      <p className="status" role="status">
        {t("plant.done.written", { written: result.tags_written, skipped: result.tags_skipped })}
      </p>
      <div className="toolbar">
        {result.loops.map((loop) => (
          <button key={loop.id} type="button" onClick={() => onOpen(result.dataset_id, loop.id)}>
            {t("plant.done.open", { loop: loop.name })}
          </button>
        ))}
        <button type="button" onClick={onReset}>{t("plant.done.reset")}</button>
      </div>
    </section>
  );
}

interface PageProps {
  /** Reloads the dataset list of the app. */
  onCreated: () => void;
  /** Opens the tuning view of a loop of a dataset. */
  onOpen: (datasetId: string, loop: string) => void;
  t: Translate;
}

/** The plant import section: read, preview, then import into a new dataset. */
export function ImportPlant({ onCreated, onOpen, t }: PageProps) {
  const state = usePlantImport(t, onCreated);
  const busyAny = state.busy !== null;
  return (
    <section>
      <header className="toolbar"><h2>{t("plant.title")}</h2></header>
      <ImportPlantNotes t={t} />
      <FileFields hasDataFile={state.dataFile !== null} onDataFile={state.setDataFile}
        onDictionaryFile={state.setDictionaryFile} t={t} />
      <div className="knowledge-fields">
        <TimeZoneField preset={state.preset} offsetHours={state.offsetHours}
          onPreset={state.setPreset} onOffset={state.setOffsetHours} t={t} />
      </div>
      <PreviewButton busy={state.busy === "preview"} canPreview={state.canPreview}
        onPreview={state.runPreview} t={t} />
      {state.error !== null && <p className="status status-error" role="alert">{state.error}</p>}
      {state.result !== null
        ? <ImportPlantDone result={state.result} onOpen={onOpen} onReset={state.reset} t={t} />
        : state.preview !== null && (
          <>
            <ImportPlantPreview preview={state.preview} t={t} />
            <ImportForm scope={state.scope} datasetId={state.datasetId} canImport={state.canImport}
              busyImport={busyAny} onScope={state.setScope} onDatasetId={state.setDatasetId}
              onImport={state.runImport} t={t} />
          </>
        )}
    </section>
  );
}

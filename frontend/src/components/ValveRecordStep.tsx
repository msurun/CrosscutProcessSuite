// src/components/ValveRecordStep.tsx
//
// Step of the valve-test wizard where the user supplies the recorded stroke
// test: either a window of the loaded dataset (picked with WindowPicker) or a
// CSV file read in the browser. Nothing is written to the plant here.

import { useState } from "react";
import type { LoopSummary } from "../api";
import type { Translate } from "../findings";
import { WindowPicker } from "./WindowPicker";

/** The two places a stroke-test recording can come from. */
type RecordingSource = "dataset" | "csv";

/** A window selected on the dataset, in seconds since the first sample. */
interface RecordingWindow {
  startS: number;
  endS: number;
}

/** Accept attribute of the CSV file input. */
const CSV_ACCEPT = ".csv,.txt,text/csv,text/plain";

/**
 * Read one radio option of the recording source.
 *
 * @returns The option's radio input with its label, wrapped in one `<label>`.
 */
function SourceOption({
  value,
  checked,
  label,
  onSelect,
}: {
  value: RecordingSource;
  checked: boolean;
  label: string;
  onSelect: (source: RecordingSource) => void;
}) {
  return (
    <label className="radio-label">
      <input
        type="radio"
        name="valve-source"
        value={value}
        checked={checked}
        onChange={() => onSelect(value)}
      />
      {label}
    </label>
  );
}

/** The dataset source: the window picker plus the "analyse" button and its hints. */
function DatasetSource({
  datasetId,
  loop,
  window,
  busy,
  onWindowChange,
  onAnalyseWindow,
  t,
}: {
  datasetId: string;
  loop: LoopSummary;
  window: RecordingWindow | null;
  busy: boolean;
  onWindowChange: (w: RecordingWindow) => void;
  onAnalyseWindow: (w: RecordingWindow) => void;
  t: Translate;
}) {
  const canAnalyse = window !== null && !busy;

  return (
    <>
      <p>{t("valve.record.fromDatasetHelp")}</p>
      <WindowPicker
        datasetId={datasetId}
        loop={loop}
        window={window}
        onSelectWindow={onWindowChange}
        t={t}
      />
      {window === null && <p className="hint">{t("valve.record.windowNeeded")}</p>}
      <button
        type="button"
        className="filter-chip"
        disabled={!canAnalyse}
        onClick={() => {
          if (window !== null) {
            onAnalyseWindow(window);
          }
        }}
      >
        {busy ? t("valve.record.analysing") : t("valve.record.analyse")}
      </button>
    </>
  );
}

/** The CSV source: the file input and the "analyse" button. */
function CsvSource({
  fileName,
  hasFile,
  busy,
  onFileChange,
  onAnalyseCsv,
  t,
}: {
  fileName: string | null;
  hasFile: boolean;
  busy: boolean;
  onFileChange: (file: File) => void;
  onAnalyseCsv: () => void;
  t: Translate;
}) {
  const canAnalyse = hasFile && !busy;

  return (
    <>
      <p>{t("valve.record.csvHelp")}</p>
      <label className="field-label">
        {t("valve.record.csvChoose")}
        <input
          type="file"
          accept={CSV_ACCEPT}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file !== undefined) {
              onFileChange(file);
            }
          }}
        />
      </label>
      {fileName !== null && <p>{t("valve.record.csvName", { name: fileName })}</p>}
      <button type="button" className="filter-chip" disabled={!canAnalyse} onClick={onAnalyseCsv}>
        {busy ? t("valve.record.analysing") : t("valve.record.analyse")}
      </button>
    </>
  );
}

/**
 * Error line shown above the buttons when the last analysis attempt failed.
 *
 * @returns The alert paragraph, or null when there is no error to show.
 */
function ErrorAlert({ errorText, t }: { errorText: string | null; t: Translate }) {
  if (errorText === null) {
    return null;
  }
  return (
    <p role="alert" className="status status-error">
      {`${t("valve.error.title")}: ${errorText}`}
    </p>
  );
}

/**
 * Step of the valve-test wizard: supply the recorded stroke test.
 *
 * The user picks one of two sources. "dataset" gives the window of an existing
 * record, chosen with {@link WindowPicker}; "csv" reads a file the user drops in
 * the browser. The chosen recording is handed up to the wizard, which runs the
 * analysis; this component never calls the API itself.
 */
export function ValveRecordStep({
  datasetId,
  loop,
  busy,
  errorText,
  onAnalyseWindow,
  onAnalyseCsv,
  onBack,
  t,
}: {
  datasetId: string;
  loop: LoopSummary;
  busy: boolean;
  errorText: string | null;
  onAnalyseWindow: (window: { startS: number; endS: number }) => void;
  onAnalyseCsv: (csvText: string) => void;
  onBack: () => void;
  t: Translate;
}) {
  const [source, setSource] = useState<RecordingSource>("dataset");
  const [window, setWindow] = useState<RecordingWindow | null>(null);
  const [csvText, setCsvText] = useState<string | null>(null);
  const [csvName, setCsvName] = useState<string | null>(null);

  // Read the file in the browser; any error is left to the server, which parses the text.
  const handleFileChange = (file: File) => {
    file
      .text()
      .then((text) => {
        setCsvText(text);
        setCsvName(file.name);
      })
      .catch((error: unknown) => {
        setCsvText(null);
        setCsvName(null);
        throw new Error(`Could not read ${file.name}: ${String(error)}`);
      });
  };

  const handleAnalyseCsv = () => {
    if (csvText !== null) {
      onAnalyseCsv(csvText);
    }
  };

  return (
    <section className="valve-record" aria-labelledby="valve-record-title">
      <h3 id="valve-record-title">{t("valve.record.title")}</h3>

      <fieldset>
        <legend>{t("valve.record.title")}</legend>
        <SourceOption
          value="dataset"
          checked={source === "dataset"}
          label={t("valve.record.fromDataset")}
          onSelect={setSource}
        />
        <SourceOption
          value="csv"
          checked={source === "csv"}
          label={t("valve.record.fromCsv")}
          onSelect={setSource}
        />
      </fieldset>

      {source === "dataset" ? (
        <DatasetSource
          datasetId={datasetId}
          loop={loop}
          window={window}
          busy={busy}
          onWindowChange={setWindow}
          onAnalyseWindow={onAnalyseWindow}
          t={t}
        />
      ) : (
        <CsvSource
          fileName={csvName}
          hasFile={csvText !== null}
          busy={busy}
          onFileChange={handleFileChange}
          onAnalyseCsv={handleAnalyseCsv}
          t={t}
        />
      )}

      <ErrorAlert errorText={errorText} t={t} />

      <button type="button" className="filter-chip" onClick={onBack}>
        {t("valve.record.back")}
      </button>
    </section>
  );
}

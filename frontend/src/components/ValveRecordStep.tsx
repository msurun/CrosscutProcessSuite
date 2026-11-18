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

/** The "analyse" button of the dataset source; enabled once a window is picked. */
function AnalyseWindowButton({
  window,
  busy,
  onAnalyseWindow,
  t,
}: {
  window: RecordingWindow | null;
  busy: boolean;
  onAnalyseWindow: (w: RecordingWindow) => void;
  t: Translate;
}) {
  return (
    <button
      type="button"
      className="filter-chip"
      disabled={window === null || busy}
      onClick={() => {
        if (window !== null) {
          onAnalyseWindow(window);
        }
      }}
    >
      {busy ? t("valve.record.analysing") : t("valve.record.analyse")}
    </button>
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
      <AnalyseWindowButton window={window} busy={busy} onAnalyseWindow={onAnalyseWindow} t={t} />
    </>
  );
}

/** The labelled CSV file input; reports the first chosen file. */
function CsvFileInput({ onFileChange, t }: { onFileChange: (file: File) => void; t: Translate }) {
  return (
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
      <CsvFileInput onFileChange={onFileChange} t={t} />
      {fileName !== null && <p>{t("valve.record.csvName", { name: fileName })}</p>}
      <button type="button" className="filter-chip" disabled={!canAnalyse} onClick={onAnalyseCsv}>
        {busy ? t("valve.record.analysing") : t("valve.record.analyse")}
      </button>
    </>
  );
}

/** Fieldset with the two recording-source radio options. */
function SourceFieldset({
  source,
  onSelect,
  t,
}: {
  source: RecordingSource;
  onSelect: (source: RecordingSource) => void;
  t: Translate;
}) {
  return (
    <fieldset>
      <legend>{t("valve.record.title")}</legend>
      <SourceOption
        value="dataset"
        checked={source === "dataset"}
        label={t("valve.record.fromDataset")}
        onSelect={onSelect}
      />
      <SourceOption
        value="csv"
        checked={source === "csv"}
        label={t("valve.record.fromCsv")}
        onSelect={onSelect}
      />
    </fieldset>
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
 * State of the CSV source: the file text read in the browser and its name.
 *
 * @returns Whether a file is loaded, its name and the two handlers.
 */
function useCsvFile(onAnalyseCsv: (csvText: string) => void) {
  const [csvText, setCsvText] = useState<string | null>(null);
  const [csvName, setCsvName] = useState<string | null>(null);

  // Read the file in the browser; any error is left to the server, which parses the text.
  const onFileChange = (file: File) => {
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

  const onAnalyse = () => {
    if (csvText !== null) {
      onAnalyseCsv(csvText);
    }
  };

  return { hasFile: csvText !== null, name: csvName, onFileChange, onAnalyse };
}

/** Props of {@link DatasetSource} except the translator. */
type DatasetProps = Omit<Parameters<typeof DatasetSource>[0], "t">;

/** Body of the step: the dataset or the CSV source, depending on the selection. */
function SourceBody({
  source,
  dataset,
  csv,
  busy,
  t,
}: {
  source: RecordingSource;
  dataset: DatasetProps;
  csv: ReturnType<typeof useCsvFile>;
  busy: boolean;
  t: Translate;
}) {
  if (source === "dataset") {
    return <DatasetSource {...dataset} t={t} />;
  }
  return (
    <CsvSource
      fileName={csv.name}
      hasFile={csv.hasFile}
      busy={busy}
      onFileChange={csv.onFileChange}
      onAnalyseCsv={csv.onAnalyse}
      t={t}
    />
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
export function ValveRecordStep(props: {
  datasetId: string;
  loop: LoopSummary;
  busy: boolean;
  errorText: string | null;
  onAnalyseWindow: (window: { startS: number; endS: number }) => void;
  onAnalyseCsv: (csvText: string) => void;
  onBack: () => void;
  t: Translate;
}) {
  const { datasetId, loop, busy, errorText, onAnalyseWindow, onAnalyseCsv, onBack, t } = props;
  const [source, setSource] = useState<RecordingSource>("dataset");
  const [window, setWindow] = useState<RecordingWindow | null>(null);
  const csv = useCsvFile(onAnalyseCsv);

  return (
    <section className="valve-record" aria-labelledby="valve-record-title">
      <h3 id="valve-record-title">{t("valve.record.title")}</h3>

      <SourceFieldset source={source} onSelect={setSource} t={t} />

      <SourceBody
        source={source}
        dataset={{
          datasetId,
          loop,
          window,
          busy,
          onWindowChange: setWindow,
          onAnalyseWindow,
        }}
        csv={csv}
        busy={busy}
        t={t}
      />

      <ErrorAlert errorText={errorText} t={t} />

      <button type="button" className="filter-chip" onClick={onBack}>
        {t("valve.record.back")}
      </button>
    </section>
  );
}

// State of the "import a plant" view: uploads, preview, scope and dataset name, and the import result.
// It keeps the upload ids so the preview and the import reuse the same server-side files, forgets
// answers of an older request and describes every failure as text for the page.
import { useCallback, useRef, useState } from "react";
import type { Translate } from "../findings";
import {
  deletePlantUpload,
  importPlant,
  previewPlant,
  timezoneBody,
  uploadPlantFile,
  validDatasetId,
  type PlantImportResult,
  type PlantPreview,
  type TzPreset,
} from "../plantImport";

/** Everything the plant import view shows and the actions on it. */
export interface PlantImportState {
  dataFile: File | null;
  dictionaryFile: File | null;
  setDataFile: (file: File | null) => void;
  setDictionaryFile: (file: File | null) => void;
  preset: TzPreset;
  setPreset: (preset: TzPreset) => void;
  offsetHours: string;
  setOffsetHours: (offsetHours: string) => void;
  preview: PlantPreview | null;
  scope: "loops" | "process";
  setScope: (scope: "loops" | "process") => void;
  datasetId: string;
  setDatasetId: (datasetId: string) => void;
  busy: "preview" | "import" | null;
  error: string | null;
  result: PlantImportResult | null;
  canPreview: boolean;
  canImport: boolean;
  runPreview: () => void;
  runImport: () => void;
  reset: () => void;
}

/** The upload ids kept from `runPreview`, reused by `runImport`. */
interface KeptUploads {
  data: string;
  dictionary: string | null;
}

/** Turns a failed request into text the page can show. */
function errorText(failure: unknown): string {
  return failure instanceof Error ? failure.message : String(failure);
}

/** Uploads the data file and the optional dictionary file, then returns their upload ids. */
async function uploadBothFiles(
  dataFile: File,
  dictionaryFile: File | null,
): Promise<KeptUploads> {
  const data = await uploadPlantFile("data", dataFile);
  if (dictionaryFile === null) return { data: data.upload_id, dictionary: null };
  const dictionary = await uploadPlantFile("dictionary", dictionaryFile);
  return { data: data.upload_id, dictionary: dictionary.upload_id };
}

/** Deletes uploaded files on the server; a failure here must not hide the user's own error. */
function discardUploads(uploads: KeptUploads | null): void {
  if (uploads === null) return;
  const ids = uploads.dictionary === null ? [uploads.data] : [uploads.data, uploads.dictionary];
  for (const uploadId of ids) deletePlantUpload(uploadId).catch(() => undefined);
}

/** The plant import state; `onCreated` runs after a successful import (the app reloads its list). */
export function usePlantImport(_t: Translate, onCreated: () => void): PlantImportState {
  const [dataFile, setDataFileState] = useState<File | null>(null);
  const [dictionaryFile, setDictionaryFileState] = useState<File | null>(null);
  const [preset, setPreset] = useState<TzPreset>("utc");
  const [offsetHours, setOffsetHours] = useState("");
  const [preview, setPreview] = useState<PlantPreview | null>(null);
  const [scope, setScope] = useState<"loops" | "process">("process");
  const [datasetId, setDatasetId] = useState("");
  const [busy, setBusy] = useState<PlantImportState["busy"]>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PlantImportResult | null>(null);
  const uploads = useRef<KeptUploads | null>(null);
  const ticket = useRef(0);

  const timezone = timezoneBody(preset, offsetHours);
  const canPreview = dataFile !== null && busy === null;
  const canImport =
    preview !== null && validDatasetId(datasetId) && timezone !== null && busy === null;

  /** Forgets everything shown for the current files and invalidates running requests. */
  const clearAnswers = useCallback(() => {
    ticket.current += 1;
    setPreview(null);
    setResult(null);
    setBusy(null);
    setError(null);
  }, []);

  /** Drops old answers and the kept upload ids, and asks the server to delete those files. */
  const forgetUploads = useCallback(() => {
    clearAnswers();
    discardUploads(uploads.current);
    uploads.current = null;
  }, [clearAnswers]);

  const chooseDataFile = useCallback((file: File | null) => {
    forgetUploads();
    setDataFileState(file);
  }, [forgetUploads]);

  const chooseDictionaryFile = useCallback((file: File | null) => {
    forgetUploads();
    setDictionaryFileState(file);
  }, [forgetUploads]);

  const runPreview = useCallback(() => {
    if (dataFile === null || timezone === null) return;
    const mine = ++ticket.current;
    setBusy("preview");
    setError(null);
    discardUploads(uploads.current);
    uploadBothFiles(dataFile, dictionaryFile)
      .then((kept) => {
        if (mine !== ticket.current) return discardUploads(kept);
        uploads.current = kept;
        return previewPlant({
          data_upload: kept.data,
          dictionary_upload: kept.dictionary,
          timezone,
        }).then((reply) => mine === ticket.current && setPreview(reply));
      })
      .catch((failure: unknown) => mine === ticket.current && setError(errorText(failure)))
      .finally(() => mine === ticket.current && setBusy(null));
  }, [dataFile, dictionaryFile, timezone]);

  const runImport = useCallback(() => {
    if (uploads.current === null || timezone === null) return;
    const mine = ++ticket.current;
    setBusy("import");
    setError(null);
    importPlant({
      data_upload: uploads.current.data,
      dictionary_upload: uploads.current.dictionary,
      timezone,
      scope,
      dataset_id: datasetId,
    })
      .then((reply) => {
        if (mine !== ticket.current) return;
        setResult(reply);
        onCreated();
      })
      .catch((failure: unknown) => mine === ticket.current && setError(errorText(failure)))
      .finally(() => mine === ticket.current && setBusy(null));
  }, [timezone, scope, datasetId, onCreated]);

  const reset = useCallback(() => {
    forgetUploads();
    setDataFileState(null);
    setDictionaryFileState(null);
    setDatasetId("");
  }, [forgetUploads]);

  return {
    dataFile, dictionaryFile, setDataFile: chooseDataFile, setDictionaryFile: chooseDictionaryFile,
    preset, setPreset, offsetHours, setOffsetHours, preview, scope, setScope, datasetId, setDatasetId,
    busy, error, result, canPreview, canImport, runPreview, runImport, reset,
  };
}

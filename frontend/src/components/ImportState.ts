// State of the Import view: the chosen text, its preview, the mapping and options the user edits,
// the check result and the created dataset. Changing the mapping or options drops an old check,
// and answers of an older request are never shown. Errors become translated text for the page.
import { useCallback, useRef, useState } from "react";
import {
  checkIntake,
  createIntakeDataset,
  previewIntake,
  type IntakeCheck,
  type IntakeCreated,
  type IntakeDatasetSpec,
  type IntakeOptions,
  type IntakePreview,
} from "../api";
import type { Translate } from "../findings";
import { defaultMapping, defaultOptions, describeIntakeError, mappingBody, MAX_CSV_BYTES, type MappingField, type MappingForm } from "../intake";

/** The text the user chose: a file or pasted. */
export interface ImportSource {
  name: string;
  size: number;
  text: string;
}

/** Everything the Import view shows and the actions on it. */
export interface ImportState {
  source: ImportSource | null;
  preview: IntakePreview | null;
  mapping: MappingForm | null;
  options: IntakeOptions | null;
  check: IntakeCheck | null;
  created: IntakeCreated | null;
  busy: "preview" | "check" | "create" | null;
  error: string | null;
  loadFile: (file: File) => void;
  loadPasted: (text: string) => void;
  setField: (field: MappingField, value: string) => void;
  setOptions: (options: IntakeOptions) => void;
  runCheck: () => void;
  create: (spec: IntakeDatasetSpec) => void;
  reset: () => void;
}

/** Reads a File as text in the browser (nothing is uploaded by this step). */
function readFileText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("read failed"));
    reader.readAsText(file);
  });
}

/** The Import state; `onCreated` runs after a dataset was created (the app reloads its list). */
export function useImport(t: Translate, onCreated: () => void): ImportState {
  const [source, setSource] = useState<ImportSource | null>(null);
  const [preview, setPreview] = useState<IntakePreview | null>(null);
  const [mapping, setMapping] = useState<MappingForm | null>(null);
  const [options, setOptionsState] = useState<IntakeOptions | null>(null);
  const [check, setCheck] = useState<IntakeCheck | null>(null);
  const [created, setCreated] = useState<IntakeCreated | null>(null);
  const [busy, setBusy] = useState<ImportState["busy"]>(null);
  const [error, setError] = useState<string | null>(null);
  const ticket = useRef(0);

  const clear = useCallback(() => {
    ticket.current += 1;
    setPreview(null);
    setMapping(null);
    setOptionsState(null);
    setCheck(null);
    setCreated(null);
    setBusy(null);
    setError(null);
  }, []);

  const startPreview = useCallback((next: ImportSource) => {
    clear();
    setSource(next);
    const mine = ticket.current;
    setBusy("preview");
    previewIntake(next.text)
      .then((reply) => {
        if (mine !== ticket.current) return;
        setPreview(reply);
        setMapping(defaultMapping(reply));
        setOptionsState(defaultOptions(reply));
      })
      .catch((failure: unknown) => mine === ticket.current && setError(describeIntakeError(failure, t)))
      .finally(() => mine === ticket.current && setBusy(null));
  }, [clear, t]);

  const loadText = useCallback((name: string, size: number, text: string) => {
    if (size > MAX_CSV_BYTES) {
      clear();
      setSource(null);
      setError(t("import.error.tooLarge"));
      return;
    }
    startPreview({ name, size, text });
  }, [clear, startPreview, t]);

  const loadFile = useCallback((file: File) => {
    if (file.size > MAX_CSV_BYTES) return loadText(file.name, file.size, "");
    readFileText(file)
      .then((text) => loadText(file.name, file.size, text))
      .catch(() => { clear(); setError(t("import.error.readFailed")); });
  }, [clear, loadText, t]);

  const loadPasted = useCallback((text: string) => {
    loadText(t("import.pasted"), new Blob([text]).size, text);
  }, [loadText, t]);

  const setField = useCallback((field: MappingField, value: string) => {
    setMapping((old) => (old === null ? old : { ...old, [field]: value }));
    setCheck(null);
  }, []);

  const setOptions = useCallback((next: IntakeOptions) => {
    setOptionsState(next);
    setCheck(null);
  }, []);

  const runCheck = useCallback(() => {
    if (source === null || preview === null || mapping === null || options === null) return;
    const mine = ++ticket.current;
    setBusy("check");
    setError(null);
    checkIntake({ csvText: source.text, mapping: mappingBody(mapping, preview.layout), options })
      .then((reply) => mine === ticket.current && setCheck(reply))
      .catch((failure: unknown) => mine === ticket.current && (setCheck(null), setError(describeIntakeError(failure, t))))
      .finally(() => mine === ticket.current && setBusy(null));
  }, [source, preview, mapping, options, t]);

  const create = useCallback((spec: IntakeDatasetSpec) => {
    if (source === null || preview === null || mapping === null || options === null) return;
    setBusy("create");
    setError(null);
    const input = { csvText: source.text, mapping: mappingBody(mapping, preview.layout), options };
    createIntakeDataset(input, spec)
      .then((reply) => { setCreated(reply); onCreated(); })
      .catch((failure: unknown) => setError(describeIntakeError(failure, t)))
      .finally(() => setBusy(null));
  }, [source, preview, mapping, options, t, onCreated]);

  const reset = useCallback(() => { clear(); setSource(null); }, [clear]);

  return { source, preview, mapping, options, check, created, busy, error, loadFile, loadPasted, setField, setOptions, runCheck, create, reset };
}

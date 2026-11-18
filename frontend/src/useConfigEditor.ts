// State for the shared configuration editor.
// Module routes perform domain validation before a document is accepted.
import { useEffect, useMemo, useState } from "react";
import { ApiError, fetchConfig, fetchSchema, saveConfig } from "./api";
import type { ConfigEditorPageProps } from "./ConfigEditorPage";
import { applyField, describeFields, type Field, type JsonDocument, type SchemaObject } from "./schemaFormModel";

interface Configuration {
  schema: SchemaObject;
  doc: JsonDocument;
  wasStored: boolean;
}

/** Load schema and document together; only a missing document starts empty. */
async function loadConfiguration(kind: string, configId: string) {
  return Promise.all([
    fetchSchema(kind),
    fetchConfig(kind, configId).catch((error: unknown) =>
      error instanceof ApiError && error.status === 404 ? null : Promise.reject(error)),
  ]);
}

/** Load an editor session and discard responses after selection or reload changes. */
function useConfiguration(kind: string, configId: string, revision: number) {
  const [loaded, setLoaded] = useState<Configuration | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setLoaded(null);
    setLoadError(null);
    void loadConfiguration(kind, configId).then(([schema, doc]) => {
      if (!cancelled) setLoaded({ schema, doc: doc ?? {}, wasStored: doc !== null });
    }).catch((error: unknown) => {
      if (!cancelled) setLoadError(error instanceof Error ? error.message : String(error));
    });
    return () => { cancelled = true; };
  }, [kind, configId, revision]);
  return { loaded, setLoaded, loadError };
}
type ConfigurationState = ReturnType<typeof useConfiguration>;

/** Keep validation and success feedback together so each new action clears both. */
function useEditorFeedback() {
  const [problemLines, setProblemLines] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);
  function clear() {
    setProblemLines([]);
    setSaved(false);
  }
  function report(error: unknown) {
    setProblemLines([error instanceof Error ? error.message : String(error)]);
  }
  return { problemLines, setProblemLines, saved, setSaved, clear, report };
}
type EditorFeedback = ReturnType<typeof useEditorFeedback>;

/** Parse field text without replacing the last valid document when parsing fails. */
function changeConfiguration(state: ConfigurationState, feedback: EditorFeedback, field: Field, text: string) {
  if (!state.loaded) return;
  try {
    state.setLoaded({ ...state.loaded, doc: applyField(state.loaded.doc, field, text) });
    feedback.clear();
  } catch (error) {
    feedback.report(error);
  }
}

/** Persist a document through its module validator and retain the server's accepted value. */
async function persistConfiguration(props: ConfigEditorPageProps, state: ConfigurationState, feedback: EditorFeedback) {
  if (!state.loaded) return;
  feedback.clear();
  try {
    const doc = await saveConfig(props.kind, props.configId, state.loaded.doc);
    state.setLoaded({ ...state.loaded, doc, wasStored: true });
    feedback.setSaved(true);
    props.onSaved?.();
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    feedback.setProblemLines(detail.includes("\n") ? detail.split("\n")
      : [props.t("configEditor.saveFailed", { detail })]);
  }
}

/** Disable duplicate saves and reload while a write is pending. */
function useConfigurationSave(props: ConfigEditorPageProps, state: ConfigurationState, feedback: EditorFeedback) {
  const [isSaving, setIsSaving] = useState(false);
  async function save() {
    if (!state.loaded || isSaving) return;
    setIsSaving(true);
    try {
      await persistConfiguration(props, state, feedback);
    } finally {
      setIsSaving(false);
    }
  }
  return { isSaving, save };
}

/** Own edits, server validation messages and explicit reload for one document. */
export function useConfigEditor(props: ConfigEditorPageProps) {
  const [revision, setRevision] = useState(0);
  const state = useConfiguration(props.kind, props.configId, revision);
  const feedback = useEditorFeedback();
  const saving = useConfigurationSave(props, state, feedback);
  const fields = useMemo(() => state.loaded
    ? describeFields(state.loaded.schema, state.loaded.doc, props.kind, props.t) : [],
  [state.loaded, props.kind, props.t]);
  function reload() {
    feedback.clear();
    setRevision((current) => current + 1);
    props.onSaved?.();
  }
  return { ...state, ...feedback, ...saving, fields, reload,
    change: (field: Field, text: string) => changeConfiguration(state, feedback, field, text) };
}

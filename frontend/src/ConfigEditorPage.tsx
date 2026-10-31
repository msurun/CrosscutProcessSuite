/**
 * Page that edits one configuration document (issue #45) through the schema-driven form:
 * loads the schema and the stored document (404 means "start empty"), applies field
 * edits with the pure logic of schemaForm.ts and saves through the config routes.
 */
import { useEffect, useMemo, useState } from "react";
import { ApiError, fetchConfig, fetchSchema, saveConfig } from "./api";
import type { Translate } from "./findings";
import { applyField, describeFields } from "./schemaFormModel";
import type { Field, JsonDocument, SchemaObject } from "./schemaFormModel";
import { SchemaForm } from "./SchemaForm";

export interface ConfigEditorPageProps {
  kind: string; // "anomaly" | "softsensor" | "supervisor" | "site"
  configId: string; // the id within the kind ("site" for the site file)
  t: Translate;
}

/** Renders a schema-driven editor for one configuration document. */
export function ConfigEditorPage({ kind, configId, t }: ConfigEditorPageProps) {
  const [schema, setSchema] = useState<SchemaObject | null>(null);
  const [doc, setDoc] = useState<JsonDocument | null>(null);
  const [wasStored, setWasStored] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [problemLines, setProblemLines] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        // A 404 on the document means nothing is stored yet: start from an empty document.
        const [schemaResult, stored] = await Promise.all([
          fetchSchema(kind),
          fetchConfig(kind, configId).catch((error: unknown) =>
            error instanceof ApiError && error.status === 404 ? null : Promise.reject(error),
          ),
        ]);
        if (cancelled) return;
        setSchema(schemaResult);
        setDoc(stored ?? {});
        setWasStored(stored !== null);
      } catch (error) {
        if (!cancelled) {
          setLoadError(error instanceof Error ? error.message : String(error));
        }
      }
    }

    load();

    return () => {
      cancelled = true;
    };
  }, [kind, configId]);

  const fields = useMemo(
    () => (schema && doc ? describeFields(schema, doc, kind, t) : []),
    [schema, doc, kind, t],
  );

  function handleFieldChange(field: Field, text: string) {
    if (doc === null) return;

    try {
      setDoc(applyField(doc, field, text));
      setProblemLines([]);
      setSaved(false);
    } catch (error) {
      setProblemLines([error instanceof Error ? error.message : String(error)]);
    }
  }

  async function handleSave() {
    if (doc === null || isSaving) return;

    setIsSaving(true);
    setProblemLines([]);
    setSaved(false);
    try {
      await saveConfig(kind, configId, doc);
      setSaved(true);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      // A multi-line message is a list of validation problems; one line per entry.
      setProblemLines(
        message.includes("\n") ? message.split("\n") : [t("configEditor.saveFailed", { detail: message })],
      );
    } finally {
      setIsSaving(false);
    }
  }

  if (loadError !== null) {
    return (
      <div>
        <p className="status status-error" role="alert">
          {loadError}
        </p>
      </div>
    );
  }

  if (schema === null || doc === null) {
    return (
      <div>
        <p className="hint">{t("configEditor.loading")}</p>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <h2>{t("configEditor.title")}</h2>
      {!wasStored && <p className="hint">{t("configEditor.notStored")}</p>}
      <SchemaForm fields={fields} onFieldChange={handleFieldChange} />
      {problemLines.length > 0 && (
        <div role="alert">
          <ul className="status status-error">
            {problemLines.map((line, index) => (
              <li key={index}>{line}</li>
            ))}
          </ul>
        </div>
      )}
      <div>
        <button type="button" className="filter-chip" onClick={handleSave} disabled={isSaving}>
          {isSaving ? t("configEditor.saving") : t("configEditor.save")}
        </button>
        {saved && <span className="hint"> {t("configEditor.saved")}</span>}
      </div>
    </div>
  );
}

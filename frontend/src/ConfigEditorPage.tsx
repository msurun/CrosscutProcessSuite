// Shared schema-driven configuration view.
// State lives in a hook so every module uses the same save and reload behaviour.
import type { Translate } from "./findings";
import { SchemaForm } from "./SchemaForm";
import { useConfigEditor } from "./useConfigEditor";

export interface ConfigEditorPageProps {
  kind: string;
  configId: string;
  t: Translate;
  onSaved?: () => void;
}

/** Render schema fields and actions for one module configuration. */
export function ConfigEditorPage(props: ConfigEditorPageProps) {
  const editor = useConfigEditor(props);
  const { t } = props;
  if (editor.loadError !== null) {
    return <p className="status status-error" role="alert">{editor.loadError}</p>;
  }
  if (editor.loaded === null) return <p className="hint">{t("configEditor.loading")}</p>;
  return (
    <section aria-label={t("configEditor.title")} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <h2>{t("configEditor.title")}</h2>
      {!editor.loaded.wasStored && <p className="hint">{t("configEditor.notStored")}</p>}
      <SchemaForm fields={editor.fields} onFieldChange={editor.change} t={t} />
      {editor.problemLines.length > 0 && <div role="alert"><ul className="status status-error">
        {editor.problemLines.map((line, index) => <li key={index}>{line}</li>)}
      </ul></div>}
      <div>
        <button type="button" className="filter-chip" onClick={editor.save} disabled={editor.isSaving}>
          {t(editor.isSaving ? "configEditor.saving" : "configEditor.save")}
        </button>
        <button type="button" className="filter-chip" onClick={editor.reload} disabled={editor.isSaving}>
          {t("configEditor.reload")}
        </button>
        {editor.saved && <span className="hint" role="status"> {t("configEditor.saved")}</span>}
      </div>
    </section>
  );
}

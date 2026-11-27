// Load a verified identified model and save an audited edited copy.
// The displayed parent is immutable; saving promotes the returned new version for further work.
import { useState } from "react";
import type { FormEvent } from "react";
import type { Translate } from "../findings";
import { loadMpcModel, saveMpcModel, type IdentModelVersion } from "../mpcModelApi";
import { draftModelPairs, isValidPair, ModelMatrixGrid, type PairDraft } from "./ModelMatrixGrid";

/** Build the full grid request, omitting the immutable fit verdicts. */
function editPairs(pairs: PairDraft[]) {
  return pairs.map((pair) => ({ input_name: pair.input_name, cv_name: pair.cv_name,
    gain: Number(pair.gain), time_constant_s: Number(pair.time_constant_s),
    dead_time_s: Number(pair.dead_time_s), enabled: pair.enabled }));
}

/** Manage loading and saving with one in-flight request and a stable parent snapshot. */
function useModelMatrix() {
  const [modelId, setModelId] = useState("");
  const [parent, setParent] = useState<IdentModelVersion | null>(null);
  const [pairs, setPairs] = useState<PairDraft[]>([]);
  const [author, setAuthor] = useState(""), [reason, setReason] = useState("");
  const [error, setError] = useState(""), [savedId, setSavedId] = useState("");
  const [busy, setBusy] = useState(false);
  function adopt(model: IdentModelVersion) { setParent(model); setPairs(draftModelPairs(model)); }
  async function request(save: boolean) {
    setBusy(true); setError(""); setSavedId("");
    try {
      const model = save && parent ? await saveMpcModel(parent.model_id, {
        parent_sha256: parent.sha256, author: author.trim(), reason: reason.trim(), pairs: editPairs(pairs),
      }) : await loadMpcModel(modelId.trim());
      adopt(model); if (save) { setSavedId(model.model_id); setReason(""); setModelId(model.model_id); }
    } catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
    finally { setBusy(false); }
  }
  return { modelId, setModelId, parent, pairs, setPairs, author, setAuthor, reason, setReason,
    error, savedId, busy, request };
}

/** Require a meaningful matrix change and an explanation before enabling Save. */
function canSave(editor: ReturnType<typeof useModelMatrix>): boolean {
  return editor.parent !== null && editor.author.trim() !== "" && editor.reason.trim() !== ""
    && editor.pairs.every(isValidPair)
    && JSON.stringify(editPairs(editor.pairs)) !== JSON.stringify(editPairs(draftModelPairs(editor.parent)));
}

/** Show lineage and the hash that will be checked again when the edited version is saved. */
function ModelLineage({ model, t }: { model: IdentModelVersion; t: Translate }) {
  return <div><p>{t("modelMatrix.version", { id: model.model_id })}</p>
    <p>{t("modelMatrix.hash", { hash: model.sha256 })}</p>
    {model.parent_model_id && <p>{t("modelMatrix.parent", { id: model.parent_model_id,
      hash: model.parent_sha256 ?? "" })}</p>}
    {model.author && <p>{t("modelMatrix.audit", { author: model.author, reason: model.reason ?? "" })}</p>}
  </div>;
}

/** Keep the audit explanation next to the editable matrix and immutable parent details. */
function ModelEditorForm({ editor, t }: { editor: ReturnType<typeof useModelMatrix>; t: Translate }) {
  const submit = (event: FormEvent) => { event.preventDefault(); void editor.request(true); };
  return editor.parent && <form onSubmit={submit}><fieldset disabled={editor.busy}>
      <ModelLineage model={editor.parent} t={t} />
      <ModelMatrixGrid parent={editor.parent} pairs={editor.pairs} onChange={editor.setPairs} t={t} />
      <label>{t("modelMatrix.author")}<input required value={editor.author}
        onChange={(event) => editor.setAuthor(event.target.value)} /></label>
      <label>{t("modelMatrix.reason")}<textarea required value={editor.reason}
        onChange={(event) => editor.setReason(event.target.value)} /></label>
      <button type="submit" disabled={!canSave(editor)}>{t("modelMatrix.save")}</button>
    </fieldset></form>;
}

/** One editor on the Steps page for identified MV/DV-to-CV paths. */
export function ModelMatrixPanel({ t }: { t: Translate }) {
  const editor = useModelMatrix();
  const submit = (event: FormEvent) => { event.preventDefault(); void editor.request(false); };
  return <section aria-label={t("modelMatrix.title")}><h3>{t("modelMatrix.title")}</h3>
    <p>{t("modelMatrix.notice")}</p>
    <form onSubmit={submit}><fieldset disabled={editor.busy}>
      <label>{t("modelMatrix.modelId")}<input required value={editor.modelId}
        onChange={(event) => editor.setModelId(event.target.value)} /></label>
      <button type="submit">{t("modelMatrix.load")}</button>
    </fieldset></form>
    <ModelEditorForm editor={editor} t={t} />
    {editor.busy && <p role="status">{t("modelMatrix.busy")}</p>}
    {editor.savedId && <p role="status">{t("modelMatrix.saved", { id: editor.savedId })}</p>}
    {editor.error && <p role="alert">{editor.error}</p>}
  </section>;
}

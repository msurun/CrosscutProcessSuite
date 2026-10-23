// Step 4 of the Import view: name the new dataset (the id is checked while typing), choose the
// process kind and units, create it, and then open it in the tuning wizard. The button is disabled
// while the record is not usable. Creating writes only a new folder in the data folder.
import { useState } from "react";
import type { IntakeCheck, IntakeCreated, IntakeDatasetSpec } from "../api";
import type { Translate } from "../findings";
import { canCreate, datasetIdError, loopNameValid } from "../intake";
import { noteLines } from "../intakeText";

interface CreateProps {
  check: IntakeCheck | null;
  busy: boolean;
  onCreate: (spec: IntakeDatasetSpec) => void;
  t: Translate;
}

/** The dataset form; `Create dataset` is enabled when the check allows it and the names are valid. */
export function ImportCreate({ check, busy, onCreate, t }: CreateProps) {
  const [id, setId] = useState("");
  const [loop, setLoop] = useState("LIC1");
  const [kind, setKind] = useState<IntakeDatasetSpec["process_kind"]>("integrating");
  const [pvUnit, setPvUnit] = useState("%");
  const [outUnit, setOutUnit] = useState("%");
  const idError = datasetIdError(id);
  const loopOk = loopNameValid(loop);
  const allowed = canCreate(check) && idError === null && loopOk && !busy;
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (allowed) onCreate({ dataset_id: id, loop_name: loop, process_kind: kind, pv_unit: pvUnit, out_unit: outUnit });
  };
  return (
    <section aria-label={t("import.step4")}>
      <h3>{t("import.step4")}</h3>
      <form className="knowledge-editor-form" onSubmit={submit}>
        <div className="knowledge-fields">
          <div className="field">
            <label className="field-label" htmlFor="import-id">{t("import.create.id")}</label>
            <input id="import-id" className="field-input" type="text" value={id} maxLength={64} onChange={(e) => setId(e.target.value)}
              aria-invalid={id !== "" && idError !== null} aria-describedby="import-id-help" autoComplete="off" />
            <span id="import-id-help" className="field-help hint">{t("import.create.idHelp")}</span>
            {id !== "" && idError !== null && <span role="alert" className="status status-error">{t(`import.id.${idError}`)}</span>}
          </div>
          <div className="field">
            <label className="field-label" htmlFor="import-loop">{t("import.create.loop")}</label>
            <input id="import-loop" className="field-input" type="text" value={loop} maxLength={64} onChange={(e) => setLoop(e.target.value)} aria-invalid={!loopOk} />
            {!loopOk && <span role="alert" className="status status-error">{t("import.id.pattern")}</span>}
          </div>
          <div className="field">
            <label className="field-label" htmlFor="import-kind">{t("import.create.kind")}</label>
            <select id="import-kind" className="field-input" value={kind} aria-describedby="import-kind-help" onChange={(e) => setKind(e.target.value as typeof kind)}>
              <option value="integrating">{t("knowledge.kind.integrating")}</option>
              <option value="self_regulating">{t("knowledge.kind.self_regulating")}</option>
            </select>
            <span id="import-kind-help" className="field-help hint">{t("knowledge.kindHelp")}</span>
          </div>
          <label className="field">
            <span className="field-label">{t("import.create.pvUnit")}</span>
            <input className="field-input" type="text" value={pvUnit} maxLength={16} onChange={(e) => setPvUnit(e.target.value)} />
          </label>
          <label className="field">
            <span className="field-label">{t("import.create.outUnit")}</span>
            <input className="field-input" type="text" value={outUnit} maxLength={16} onChange={(e) => setOutUnit(e.target.value)} />
          </label>
        </div>
        <div className="toolbar">
          <button type="submit" disabled={!allowed}>{busy ? t("import.create.running") : t("import.create.run")}</button>
          {check === null && <span className="hint">{t("import.create.needCheck")}</span>}
          {check !== null && !canCreate(check) && <span className="hint">{t("import.create.notUsable")}</span>}
        </div>
      </form>
    </section>
  );
}

interface DoneProps {
  created: IntakeCreated;
  onOpen: (datasetId: string, loop: string) => void;
  onReset: () => void;
  t: Translate;
}

/** The success state: what the reader assumed and the way into the Tuning view. */
export function ImportDone({ created, onOpen, onReset, t }: DoneProps) {
  const loop = created.loops[0]?.name ?? "LIC1";
  return (
    <section aria-label={t("import.done.title")} data-testid="import-done">
      <h3>{t("import.done.title")}</h3>
      <p className="status" role="status">{t("import.done.text", { id: created.dataset_id })}</p>
      <h4>{t("import.readAs")}</h4>
      <ul>{noteLines(created.assumption_notes, created.assumptions, t).map((note) => <li key={note}>{note}</li>)}</ul>
      <div className="toolbar">
        <button type="button" onClick={() => onOpen(created.dataset_id, loop)}>{t("import.done.open")}</button>
        <button type="button" onClick={onReset}>{t("import.done.again")}</button>
      </div>
    </section>
  );
}

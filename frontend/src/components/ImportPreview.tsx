// Step 2 of the Import view: the first rows of the file, the detected layout and format as editable
// selects, and the signal mapping (columns for a wide file, tags for a long one) pre-filled from the
// server's guesses. The labels use plain words ("Process variable (level)").
import type { IntakeOptions, IntakePreview } from "../api";
import type { Translate } from "../findings";
import { delimiterName } from "../intakeText";
import { requiredFields, type MappingField, type MappingForm } from "../intake";

const DELIMITERS = [",", ";", "\t", "|"];
const WIDE_FIELDS: MappingField[] = ["time_col", "pv_col", "out_col", "sp_col", "mode_col"];
const LONG_FIELDS: MappingField[] = ["time_col", "tag_col", "value_col", "tag_pv", "tag_out", "tag_sp", "tag_mode"];
const TAG_FIELDS: MappingField[] = ["tag_pv", "tag_out", "tag_sp", "tag_mode"];

interface PickProps {
  label: string;
  value: string;
  choices: { value: string; label: string }[];
  onChange: (value: string) => void;
  optionalText?: string;
}

/** A labelled select; an optional one (with `optionalText`) offers an empty "not used" choice. */
function Pick({ label, value, choices, onChange, optionalText }: PickProps) {
  const emptyChoice = optionalText !== undefined || value === "";
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <select className="field-input" value={value} onChange={(event) => onChange(event.target.value)}>
        {emptyChoice && <option value="">{optionalText ?? ""}</option>}
        {choices.map((choice) => <option key={choice.value} value={choice.value}>{choice.label}</option>)}
      </select>
    </label>
  );
}

/** The first rows of the file as a table. */
function PreviewTable({ preview, t }: { preview: IntakePreview; t: Translate }) {
  return (
    <div className="table-scroll">
      <table className="loops-table">
        <caption>{t("import.preview.caption", { rows: preview.rows.length, total: preview.n_rows_estimate })}</caption>
        <thead><tr>{preview.columns.map((column, i) => <th key={`${column}-${i}`} scope="col">{column}</th>)}</tr></thead>
        <tbody>
          {preview.rows.map((row, r) => <tr key={r}>{row.map((cell, c) => <td key={c}>{cell}</td>)}</tr>)}
        </tbody>
      </table>
    </div>
  );
}

interface FormatProps {
  preview: IntakePreview;
  options: IntakeOptions;
  onOptions: (options: IntakeOptions) => void;
  t: Translate;
}

/** Layout (read-only) and the three format selects. */
function FormatFields({ preview, options, onOptions, t }: FormatProps) {
  const auto = { value: "auto", label: t("import.auto") };
  const delimiters = Array.from(new Set([preview.delimiter, ...DELIMITERS]));
  return (
    <div className="knowledge-fields">
      <p className="field"><span className="field-label">{t("import.layout")}</span><span>{t(`import.layout.${preview.layout}`)}</span></p>
      <Pick label={t("import.delimiter")} value={options.delimiter} onChange={(v) => onOptions({ ...options, delimiter: v })}
        choices={[auto, ...delimiters.map((d) => ({ value: d, label: delimiterName(d, t) }))]} />
      <Pick label={t("import.decimal")} value={options.decimal} onChange={(v) => onOptions({ ...options, decimal: v as IntakeOptions["decimal"] })}
        choices={[auto, { value: "comma", label: t("import.decimal.comma") }, { value: "dot", label: t("import.decimal.dot") }]} />
      <Pick label={t("import.timeFormat")} value={options.time_format} onChange={(v) => onOptions({ ...options, time_format: v as IntakeOptions["time_format"] })}
        choices={[auto, { value: "iso", label: t("import.time.iso") }, { value: "seconds", label: t("import.time.seconds") }]} />
    </div>
  );
}

interface MapProps {
  preview: IntakePreview;
  mapping: MappingForm;
  onField: (field: MappingField, value: string) => void;
  t: Translate;
}

/** The mapping selects of the layout in use. */
function MappingFields({ preview, mapping, onField, t }: MapProps) {
  const fields = preview.layout === "long" ? LONG_FIELDS : WIDE_FIELDS;
  const required = requiredFields(preview.layout);
  return (
    <div className="knowledge-fields">
      {fields.map((field) => (
        <Pick key={field} label={t(`import.map.${field}`)} value={mapping[field]}
          optionalText={required.includes(field) ? undefined : t("import.notUsed")}
          choices={(TAG_FIELDS.includes(field) ? preview.tags : preview.columns).map((name) => ({ value: name, label: name }))}
          onChange={(v) => onField(field, v)} />
      ))}
    </div>
  );
}

interface PreviewProps extends MapProps {
  options: IntakeOptions;
  onOptions: (options: IntakeOptions) => void;
}

/** Table, format selects and mapping selects. */
export function ImportPreview({ preview, mapping, options, onField, onOptions, t }: PreviewProps) {
  return (
    <section aria-label={t("import.step2")}>
      <h3>{t("import.step2")}</h3>
      <PreviewTable preview={preview} t={t} />
      <FormatFields preview={preview} options={options} onOptions={onOptions} t={t} />
      <h4>{t("import.mapping")}</h4>
      <MappingFields preview={preview} mapping={mapping} onField={onField} t={t} />
    </section>
  );
}

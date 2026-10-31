/**
 * Presentational editor for one schema-described field (issue #45).
 * Receives a fully resolved Field (label and help are already translated strings)
 * and reports every editor change as text through onTextChange.
 */
import type { Field } from "./schemaFormModel";

export interface SchemaFieldProps {
  field: Field;
  onTextChange: (text: string) => void;
}

/** Renders one labelled editor chosen from the field kind. */
export function SchemaField({ field, onTextChange }: SchemaFieldProps) {
  const inputId = `schema-field-${field.name}`;
  const labelText = field.required ? `${field.label} *` : field.label;

  return (
    <div className="field">
      <label className="field-label" htmlFor={inputId}>
        {labelText}
      </label>

      {field.help && <p className="field-help">{field.help}</p>}

      {field.kind === "input" && field.inputType === "string" && (
        <input
          className="field-input"
          id={inputId}
          type="text"
          value={field.text}
          onChange={(event) => onTextChange(event.target.value)}
        />
      )}

      {field.kind === "input" && field.inputType === "number" && (
        <input
          className="field-input"
          id={inputId}
          type="number"
          value={field.text}
          min={field.minimum ?? undefined}
          max={field.maximum ?? undefined}
          onChange={(event) => onTextChange(event.target.value)}
        />
      )}

      {field.kind === "input" && field.inputType === "boolean" && (
        <input
          id={inputId}
          type="checkbox"
          checked={field.text === "true"}
          onChange={(event) => onTextChange(event.target.checked ? "true" : "false")}
        />
      )}

      {field.kind === "enum" && (
        <select
          className="field-input"
          id={inputId}
          value={field.text}
          onChange={(event) => onTextChange(event.target.value)}
        >
          {field.options.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      )}

      {field.kind === "scalarArray" && (
        <textarea
          className="field-input"
          id={inputId}
          rows={4}
          value={field.text}
          onChange={(event) => onTextChange(event.target.value)}
        />
      )}

      {field.kind === "json" && (
        <textarea
          className="field-input"
          id={inputId}
          rows={8}
          value={field.text}
          onChange={(event) => onTextChange(event.target.value)}
        />
      )}
    </div>
  );
}

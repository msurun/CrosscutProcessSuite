/**
 * The schema-driven form (issue #45): renders the flat field list produced by
 * describeFields and reports each field's edited text to the owner.
 */
import { SchemaField } from "./SchemaField";
import type { Field } from "./schemaFormModel";

export interface SchemaFormProps {
  fields: Field[];
  onFieldChange: (field: Field, text: string) => void;
}

/** Displays the schema fields in order, each wired to the change handler. */
export function SchemaForm({ fields, onFieldChange }: SchemaFormProps) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {fields.map((field) => (
        <SchemaField
          key={field.name}
          field={field}
          onTextChange={(text) => onFieldChange(field, text)}
        />
      ))}
    </div>
  );
}

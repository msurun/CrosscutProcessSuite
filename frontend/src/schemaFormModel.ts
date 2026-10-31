/**
 * Pure logic for the schema-driven config form (issue #45).
 * Turns a documented JSON Schema subset plus the current document into a flat list
 * of editable fields, and applies a field's edited text back to the document.
 * No React, no DOM, no side effects.
 */

export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };
export type JsonDocument = { [key: string]: JsonValue };

export interface SchemaObject {
  type?: string;
  properties?: Record<string, SchemaObject>;
  required?: string[];
  items?: SchemaObject;
  enum?: JsonValue[];
  minimum?: number;
  maximum?: number;
  default?: JsonValue;
  title?: string;
  description?: string;
  $ref?: string;
  $defs?: Record<string, SchemaObject>;
  [key: string]: unknown;
}

export type Translate = (key: string, params?: Record<string, string | number>) => string;

export type FieldKind = "input" | "enum" | "scalarArray" | "json";

export interface Field {
  name: string; // top-level property name
  kind: FieldKind;
  inputType: "string" | "number" | "boolean"; // for kind "input"; "string" for the others
  options: string[]; // enum choices (strings); [] otherwise
  minimum: number | null;
  maximum: number | null;
  required: boolean;
  label: string; // resolved label, see resolveLabel
  help: string; // the schema description, "" when absent
  text: string; // the current value rendered as text for the editor
  numericItems: boolean; // true when scalarArray items are numeric
}

/** Resolve a $ref of the form "#/$defs/<name>". Throws for any other ref form. */
export function resolveRef(schema: SchemaObject, ref: string): SchemaObject {
  const prefix = "#/$defs/";
  if (!ref.startsWith(prefix)) {
    throw new Error(`Unsupported $ref "${ref}"; only "#/$defs/<name>" is supported.`);
  }
  const name = ref.slice(prefix.length);
  const defs = schema.$defs ?? {};
  if (!(name in defs)) {
    throw new Error(`$ref "${ref}" not found in schema.$defs.`);
  }
  return defs[name];
}

/** Resolve a $ref on the schema when present, otherwise the schema itself. */
function resolvedOf(schema: SchemaObject): SchemaObject {
  return schema.$ref ? resolveRef(schema, schema.$ref) : schema;
}

/** Determine the field kind for a schema, resolving $ref first. */
export function fieldKind(schema: SchemaObject): FieldKind {
  const resolved = resolvedOf(schema);

  if (resolved.enum !== undefined) return "enum";
  if (resolved.type === "object") return "json";
  if (resolved.type === "array") {
    const items = resolved.items;
    if (items) {
      const itemsType = resolvedOf(items).type;
      if (itemsType === "string" || itemsType === "number" || itemsType === "integer") {
        return "scalarArray";
      }
    }
    return "json";
  }
  return "input"; // boolean, number, integer, string, or missing type
}

/**
 * The input type of a scalar property: the declared type, or — when the schema states no
 * type (for example an anyOf of const and integer) — the type of the stated default.
 */
function scalarInputType(resolved: SchemaObject): "string" | "number" | "boolean" {
  const declared = resolved.type ?? (resolved.default !== undefined ? typeof resolved.default : undefined);
  if (declared === "number") return "number";
  if (declared === "boolean") return "boolean";
  return "string";
}

/** Resolve a label: translation first, then title, then raw name. */
export function resolveLabel(key: string, translated: string, title: string | undefined, name: string): string {
  if (translated !== key) return translated;
  if (title !== undefined) return title;
  return name;
}

/** True when the value is an array whose items are strings, numbers, booleans or null. */
function isScalarArray(value: JsonValue): value is (string | number | boolean | null)[] {
  return (
    Array.isArray(value) &&
    value.every(
      (item) =>
        typeof item === "string" || typeof item === "number" || item === null || typeof item === "boolean",
    )
  );
}

/** Render the current value of a property to editable text. */
function renderText(value: JsonValue, kind: FieldKind): string {
  if (kind === "scalarArray") {
    // A value that is not a usable scalar array degrades to JSON text.
    if (!isScalarArray(value)) return JSON.stringify(value, null, 2);
    return value.map((item) => String(item)).join("\n");
  }
  if (kind === "json") return JSON.stringify(value, null, 2);
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return value;
  // Fallback for null / missing
  return "";
}

/** Parse edited text for a scalarArray field into string or number items. */
function parseScalarArray(text: string, numericItems: boolean): JsonValue[] {
  const result: JsonValue[] = [];
  for (const rawLine of text.split("\n")) {
    const line = rawLine.trim();
    if (line === "") continue;
    if (numericItems) {
      const number = Number(line);
      if (!Number.isFinite(number)) {
        throw new Error(`"${line}" is not a valid number for a numeric array item.`);
      }
      result.push(number);
    } else {
      result.push(line);
    }
  }
  return result;
}

/** Create one Field descriptor from a top-level property schema and its value. */
function describeField(
  name: string,
  propertySchema: SchemaObject,
  value: JsonValue,
  schemaName: string,
  required: boolean,
  t: Translate,
): Field {
  const resolved = resolvedOf(propertySchema);
  const kind = fieldKind(propertySchema);
  const inputType = scalarInputType(resolved);

  const options = resolved.enum ? resolved.enum.map((item) => String(item)) : [];

  const itemsAreNumeric =
    resolved.items !== undefined && ["number", "integer"].includes(resolvedOf(resolved.items).type ?? "");
  const currentIsNumeric =
    Array.isArray(value) && value.length > 0 && value.every((item) => typeof item === "number");
  const numericItems = kind === "scalarArray" && (itemsAreNumeric || currentIsNumeric);

  const labelKey = `schema.${schemaName}.${name}`;
  const label = resolveLabel(labelKey, t(labelKey), resolved.title, name);
  const help = resolved.description ?? "";

  // Default value when the property is absent from the document.
  let displayValue: JsonValue = value;
  if (displayValue === undefined) {
    if (kind === "enum" && options.length > 0) {
      displayValue = options[0];
    } else if (kind === "scalarArray") {
      displayValue = [];
    } else if (kind === "json") {
      displayValue = {};
    } else if (inputType === "number") {
      displayValue = 0;
    } else if (inputType === "boolean") {
      displayValue = false;
    } else {
      displayValue = "";
    }
  }

  // Degrade a scalarArray whose current value is not a usable scalar array to JSON editing.
  let effectiveKind = kind;
  let effectiveNumericItems = numericItems;
  if (kind === "scalarArray" && !isScalarArray(displayValue)) {
    effectiveKind = "json";
    effectiveNumericItems = false;
  }

  return {
    name,
    kind: effectiveKind,
    inputType,
    options,
    minimum: resolved.minimum ?? null,
    maximum: resolved.maximum ?? null,
    required,
    label,
    help,
    text: renderText(displayValue, effectiveKind),
    numericItems: effectiveNumericItems,
  };
}

/** Build the flat list of editable fields for a schema and current document. */
export function describeFields(
  schema: SchemaObject,
  doc: JsonDocument,
  schemaName: string,
  t: Translate,
): Field[] {
  const properties = schema.properties ?? {};
  const requiredNames = schema.required ?? [];

  return Object.entries(properties).map(([name, propertySchema]) =>
    describeField(name, propertySchema, doc[name], schemaName, requiredNames.includes(name), t),
  );
}

/** Apply an edited text value to one field, returning a new document. */
export function applyField(doc: JsonDocument, field: Field, text: string): JsonDocument {
  const newDoc: JsonDocument = { ...doc };

  if (field.kind === "input") {
    if (field.inputType === "string") {
      newDoc[field.name] = text;
    } else if (field.inputType === "number") {
      const number = Number(text);
      newDoc[field.name] = text === "" || !Number.isFinite(number) ? null : number;
    } else if (field.inputType === "boolean") {
      newDoc[field.name] = text === "true";
    }
  } else if (field.kind === "enum") {
    if (!field.options.includes(text)) {
      throw new Error(`"${text}" is not one of the allowed options: ${field.options.join(", ")}.`);
    }
    newDoc[field.name] = text;
  } else if (field.kind === "scalarArray") {
    newDoc[field.name] = parseScalarArray(text, field.numericItems);
  } else if (field.kind === "json") {
    try {
      newDoc[field.name] = JSON.parse(text) as JsonValue;
    } catch (error) {
      if (error instanceof Error) {
        throw new Error(`Invalid JSON for field "${field.name}": ${error.message}`);
      }
      throw error;
    }
  }

  return newDoc;
}

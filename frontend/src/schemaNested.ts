/**
 * Pure helpers for nested schema forms (issue #127): decide whether a JSON Schema
 * object/array can be rendered as form controls and build default values for new rows.
 * Schemas the generator cannot render fall back to the advanced raw JSON editor.
 */
import { resolveRef, type JsonValue, type SchemaObject } from "./schemaFormModel";

const MAX_DEPTH = 6;
const UNSUPPORTED = ["oneOf", "anyOf", "allOf", "not", "if", "patternProperties", "propertyNames"];
const SCALARS = ["string", "number", "integer", "boolean"];

/** Resolve a "#/$defs/..." reference on the schema when present. */
export function resolveNode(schema: SchemaObject, root: SchemaObject): SchemaObject {
  return schema.$ref ? resolveRef(root, schema.$ref) : schema;
}

/** True when additionalProperties asks for free-form keys the form cannot offer. */
function hasDynamicKeys(schema: SchemaObject): boolean {
  const extra = schema.additionalProperties;
  return typeof extra === "object" && extra !== null;
}

function isSimpleObject(node: SchemaObject, root: SchemaObject, depth: number): boolean {
  const properties = node.properties;
  if (!properties || hasDynamicKeys(node)) return false;
  return Object.values(properties).every((child) => isRenderable(child, root, depth + 1));
}

/** True when the schema can be edited with generated controls. */
export function isRenderable(schema: SchemaObject, root: SchemaObject, depth = 0): boolean {
  if (depth > MAX_DEPTH) return false;
  let node: SchemaObject;
  try {
    node = resolveNode(schema, root);
  } catch {
    return false;
  }
  if (UNSUPPORTED.some((key) => key in node)) return false;
  if (node.enum !== undefined) return true;
  if (node.type === "object") return isSimpleObject(node, root, depth);
  if (node.type === "array") return node.items !== undefined && isRenderable(node.items, root, depth + 1);
  return typeof node.type === "string" && SCALARS.includes(node.type);
}

/** Value for a freshly added row or missing property of the given schema. */
export function defaultFor(schema: SchemaObject, root: SchemaObject, depth = 0): JsonValue {
  const node = resolveNode(schema, root);
  if (node.default !== undefined) return node.default;
  if (node.enum !== undefined) return node.enum[0] ?? null;
  if (node.type === "array") return [];
  if (node.type === "object" && depth <= MAX_DEPTH) {
    const entries = Object.entries(node.properties ?? {}).map(
      ([name, child]) => [name, defaultFor(child, root, depth + 1)] as const);
    return Object.fromEntries(entries);
  }
  if (node.type === "boolean") return false;
  if (node.type === "number" || node.type === "integer") return 0;
  return "";
}

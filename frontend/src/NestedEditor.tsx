/**
 * Recursive form controls generated from a JSON Schema node (issue #127):
 * a fieldset per object, add/remove rows per array, inputs for scalars.
 * Only schemas accepted by isRenderable reach this component.
 */
import { defaultFor, resolveNode } from "./schemaNested";
import type { JsonValue, SchemaObject, Translate } from "./schemaFormModel";

export interface NestedEditorProps {
  schema: SchemaObject;
  root: SchemaObject;
  value: JsonValue;
  path: string; // dotted path, used for ids and data-testid
  label: string;
  t: Translate;
  onChange: (value: JsonValue) => void;
}

type NodeProps = NestedEditorProps & { node: SchemaObject };
type ObjectValue = { [key: string]: JsonValue };

function asObject(value: JsonValue): ObjectValue {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value : {};
}

/** Parse number text; an empty or invalid entry becomes null. */
function numberOrNull(text: string): JsonValue {
  return text === "" || !Number.isFinite(Number(text)) ? null : Number(text);
}

/** Select control for an enum node. */
function EnumControl({ node, value, path, label, onChange }: NodeProps) {
  const id = `schema-field-${path}`;
  const pick = (text: string) => node.enum?.find((item) => String(item) === text) ?? null;
  return (
    <select className="field-input" id={id} aria-label={label} data-testid={id}
      value={String(value ?? "")} onChange={(event) => onChange(pick(event.target.value))}>
      {(node.enum ?? []).map((item) => <option key={String(item)} value={String(item)}>{String(item)}</option>)}
    </select>
  );
}

/** Controls for one scalar or enum value. */
function ScalarControl(props: NodeProps) {
  const { node, value, path, label, onChange } = props;
  const id = `schema-field-${path}`;
  if (node.enum !== undefined) return <EnumControl {...props} />;
  if (node.type === "boolean") {
    return <input id={id} data-testid={id} type="checkbox" aria-label={label} checked={value === true}
      onChange={(event) => onChange(event.target.checked)} />;
  }
  const numeric = node.type === "number" || node.type === "integer";
  return (
    <input className="field-input" id={id} data-testid={id} aria-label={label}
      type={numeric ? "number" : "text"} value={value === null || value === undefined ? "" : String(value)}
      onChange={(event) => onChange(numeric ? numberOrNull(event.target.value) : event.target.value)} />
  );
}

/** One fieldset per object, one control per property. */
function ObjectEditor(props: NodeProps) {
  const { node, root, value, path, t, onChange } = props;
  const current = asObject(value);
  return (
    <fieldset className="field" data-testid={`schema-object-${path}`}>
      <legend>{props.label}</legend>
      {Object.entries(node.properties ?? {}).map(([name, child]) => (
        <NestedEditor key={name} schema={child} root={root} t={t} path={`${path}.${name}`}
          label={resolveNode(child, root).title ?? name}
          value={current[name] ?? defaultFor(child, root)}
          onChange={(next) => onChange({ ...current, [name]: next })} />
      ))}
    </fieldset>
  );
}

/** Rows with add and remove buttons for an array of objects or scalars. */
function ArrayEditor(props: NodeProps) {
  const { node, root, value, path, label, t, onChange } = props;
  const rows = Array.isArray(value) ? value : [];
  const items = node.items ?? {};
  return (
    <fieldset className="field" data-testid={`schema-array-${path}`}>
      <legend>{label}</legend>
      {rows.map((row, index) => (
        <div key={index} data-testid={`schema-row-${path}.${index}`}>
          <NestedEditor schema={items} root={root} t={t} path={`${path}.${index}`}
            label={`${label} ${index + 1}`} value={row}
            onChange={(next) => onChange(rows.map((old, at) => (at === index ? next : old)))} />
          <button type="button" className="filter-chip" data-testid={`schema-remove-${path}.${index}`}
            onClick={() => onChange(rows.filter((_, at) => at !== index))}>
            {t("configEditor.removeRow")}
          </button>
        </div>
      ))}
      <button type="button" className="filter-chip" data-testid={`schema-add-${path}`}
        onClick={() => onChange([...rows, defaultFor(items, root)])}>
        {t("configEditor.addRow")}
      </button>
    </fieldset>
  );
}

/** Render the control that matches the schema node. */
export function NestedEditor(props: NestedEditorProps) {
  const node = resolveNode(props.schema, props.root);
  if (node.type === "object") return <ObjectEditor {...props} node={node} />;
  if (node.type === "array") return <ArrayEditor {...props} node={node} />;
  return (
    <div className="field">
      <label className="field-label" htmlFor={`schema-field-${props.path}`}>{props.label}</label>
      <ScalarControl {...props} node={node} />
    </div>
  );
}

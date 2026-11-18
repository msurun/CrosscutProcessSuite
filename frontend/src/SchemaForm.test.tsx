// Tests for the schema form: raw JSON buffer and generated nested controls (issue #127).
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { translate } from "./i18n";
import { SchemaForm } from "./SchemaForm";
import { describeFields, type JsonDocument, type SchemaObject } from "./schemaFormModel";

const t = (key: string, params?: Record<string, string | number>) => translate("en", key, params);
afterEach(cleanup);

const schema: SchemaObject = {
  type: "object",
  properties: {
    limits: { type: "object", properties: { lo: { type: "number" }, hi: { type: "number" } } },
    catalogue: {
      type: "array",
      items: { type: "object", properties: { tag: { type: "string" }, on: { type: "boolean" } } },
    },
    free: { type: "object", additionalProperties: { type: "object" } },
  },
};

function setup(doc: JsonDocument) {
  const fields = describeFields(schema, doc, "demo", t);
  const onFieldChange = vi.fn();
  render(<SchemaForm fields={fields} onFieldChange={onFieldChange} t={t} />);
  return onFieldChange;
}

it("keeps incomplete raw JSON text, shows the error and does not commit it", () => {
  const onFieldChange = setup({ free: { a: {} } });
  const box = screen.getByRole("textbox") as HTMLTextAreaElement;
  fireEvent.change(box, { target: { value: '{"enabled":' } });
  expect(box.value).toBe('{"enabled":');
  expect(screen.getByRole("alert").textContent).toContain("Invalid JSON");
  expect(onFieldChange).not.toHaveBeenCalled();
  fireEvent.change(box, { target: { value: '{"enabled": true}' } });
  expect(onFieldChange).toHaveBeenCalledWith(expect.objectContaining({ name: "free" }), '{"enabled": true}');
  expect(screen.queryByRole("alert")).toBeNull();
});

it("renders objects and arrays of objects as nested controls without raw JSON", () => {
  const onFieldChange = setup({ limits: { lo: 1, hi: 2 }, catalogue: [{ tag: "A", on: true }] });
  expect(screen.getByTestId("schema-object-limits")).toBeTruthy();
  fireEvent.change(screen.getByTestId("schema-field-limits.hi"), { target: { value: "5" } });
  expect(onFieldChange).toHaveBeenLastCalledWith(expect.objectContaining({ name: "limits" }), '{"lo":1,"hi":5}');
  fireEvent.click(screen.getByTestId("schema-add-catalogue"));
  expect(onFieldChange).toHaveBeenLastCalledWith(
    expect.objectContaining({ name: "catalogue" }), '[{"tag":"A","on":true},{"tag":"","on":false}]');
  fireEvent.click(screen.getByTestId("schema-remove-catalogue.0"));
  expect(onFieldChange).toHaveBeenLastCalledWith(expect.objectContaining({ name: "catalogue" }), "[]");
});

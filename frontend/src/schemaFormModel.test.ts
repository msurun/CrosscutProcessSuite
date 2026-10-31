// Tests of the pure logic of the schema-driven config form (issue #45).
// No React, no DOM, no side effects.

import { describe, expect, it } from "vitest";
import {
  fieldKind,
  resolveRef,
  resolveLabel,
  describeFields,
  applyField,
  type Field,
  type JsonDocument,
  type SchemaObject,
  type Translate,
} from "./schemaFormModel";

describe("fieldKind", () => {
  it("returns 'input' for string, number, boolean types", () => {
    expect(fieldKind({ type: "string" })).toBe("input");
    expect(fieldKind({ type: "number" })).toBe("input");
    expect(fieldKind({ type: "boolean" })).toBe("input");
  });

  it("returns 'json' for object type", () => {
    expect(fieldKind({ type: "object" })).toBe("json");
  });

  it("returns 'scalarArray' for array with string items", () => {
    expect(fieldKind({ type: "array", items: { type: "string" } })).toBe("scalarArray");
  });

  it("returns 'json' for array with object items", () => {
    expect(fieldKind({ type: "array", items: { type: "object" } })).toBe("json");
  });

  it("returns 'enum' for enum type", () => {
    expect(fieldKind({ enum: ["a", "b", "c"] })).toBe("enum");
  });

  it("resolves $ref to $defs and returns the kind of the target", () => {
    const schema: SchemaObject = {
      $defs: {
        target: { type: "string" },
      },
      $ref: "#/$defs/target",
    };
    expect(fieldKind(schema)).toBe("input");
  });

  it("throws for $ref to non-#/$defs target", () => {
    const schema: SchemaObject = {
      $ref: "external",
    };
    expect(() => fieldKind(schema)).toThrow("Unsupported $ref");
  });
});

describe("resolveRef", () => {
  it("resolves #/$defs/<name>", () => {
    const schema: SchemaObject = {
      $defs: {
        target: { type: "string" },
      },
    };
    expect(resolveRef(schema, "#/$defs/target")).toEqual({ type: "string" });
  });

  it("throws for external ref", () => {
    const schema: SchemaObject = {};
    expect(() => resolveRef(schema, "external")).toThrow("Unsupported $ref");
  });

  it("throws for missing name in $defs", () => {
    const schema: SchemaObject = {
      $defs: {},
    };
    expect(() => resolveRef(schema, "#/$defs/missing")).toThrow('not found in schema.$defs');
  });
});

describe("resolveLabel", () => {
  it("returns the translation when it differs from the key", () => {
    expect(resolveLabel("key", "translation", "title", "name")).toBe("translation");
  });

  it("returns the title when the translation equals the key", () => {
    expect(resolveLabel("key", "key", "title", "name")).toBe("title");
  });

  it("returns the name when both translation and title are absent", () => {
    expect(resolveLabel("key", "key", undefined, "name")).toBe("name");
  });
});

describe("describeFields", () => {
  const schema: SchemaObject = {
    properties: {
      stringProp: { type: "string", title: "String Property", description: "A string property" },
      numberProp: { type: "number", title: "Number Property", description: "A number property" },
      booleanProp: { type: "boolean", title: "Boolean Property", description: "A boolean property" },
      enumProp: { enum: ["a", "b", "c"], title: "Enum Property", description: "An enum property" },
      scalarArrayProp: { type: "array", items: { type: "string" }, title: "Scalar Array Property", description: "A scalar array property" },
      jsonProp: { type: "object", title: "JSON Property", description: "A JSON property" },
      numericDefaultProp: { default: 42, title: "Numeric Default Property", description: "A property with a numeric default" },
      degradedScalarArrayProp: { type: "array", items: { type: "string" }, title: "Degraded Scalar Array Property", description: "A degraded scalar array property" },
    },
    required: ["stringProp", "numberProp"],
  };

  const doc: JsonDocument = {
    stringProp: "value",
    numberProp: 42,
    booleanProp: true,
    enumProp: "a",
    scalarArrayProp: ["a", "b", "c"],
    jsonProp: { key: "value" },
    degradedScalarArrayProp: { key: "value" },
  };

  const schemaName = "testSchema";

  const t: Translate = (key: string) => key;

  const fields = describeFields(schema, doc, schemaName, t);

  it("property order follows the schema", () => {
    expect(fields.map((field) => field.name)).toEqual([
      "stringProp",
      "numberProp",
      "booleanProp",
      "enumProp",
      "scalarArrayProp",
      "jsonProp",
      "numericDefaultProp",
      "degradedScalarArrayProp",
    ]);
  });

  it("required flag from schema.required", () => {
    expect(fields[0].required).toBe(true);
    expect(fields[1].required).toBe(true);
    expect(fields[2].required).toBe(false);
  });

  it("label via t(`schema.<name>.<path>`) with title/name fallback", () => {
    const tWithMap: Translate = (key: string) => {
      const map: Record<string, string> = {
        "schema.testSchema.stringProp": "Translated String Property",
      };
      return map[key] || key;
    };
    const fieldsWithMap = describeFields(schema, doc, schemaName, tWithMap);
    expect(fieldsWithMap[0].label).toBe("Translated String Property");
    expect(fields[1].label).toBe("Number Property");
    expect(fields[2].label).toBe("Boolean Property");
  });

  it("help is the raw description text", () => {
    expect(fields[0].help).toBe("A string property");
    expect(fields[1].help).toBe("A number property");
    expect(fields[2].help).toBe("A boolean property");
  });

  it("minimum/maximum pass through as null when absent", () => {
    expect(fields[0].minimum).toBeNull();
    expect(fields[0].maximum).toBeNull();
  });

  it("missing property defaults", () => {
    const emptyDoc: JsonDocument = {};
    const emptyFields = describeFields(schema, emptyDoc, schemaName, t);
    expect(emptyFields[0].text).toBe("");
    expect(emptyFields[1].text).toBe("0");
    expect(emptyFields[2].text).toBe("false");
    expect(emptyFields[3].text).toBe("a");
    expect(emptyFields[4].text).toBe("");
    expect(emptyFields[5].text).toBe("{}");
  });

  it("number values render via String", () => {
    expect(fields[1].text).toBe("42");
  });

  it("boolean renders 'true'/'false'", () => {
    expect(fields[2].text).toBe("true");
  });

  it("scalarArray renders items joined with newlines", () => {
    expect(fields[4].text).toBe("a\nb\nc");
  });

  it("a property with no type but a numeric default gets inputType 'number'", () => {
    expect(fields[6].inputType).toBe("number");
  });

  it("a scalarArray property whose current value is not an array degrades to kind 'json'", () => {
    expect(fields[7].kind).toBe("json");
  });
});

describe("applyField", () => {
  const doc: JsonDocument = {
    stringProp: "value",
    numberProp: 42,
    booleanProp: true,
    enumProp: "a",
    scalarArrayProp: ["a", "b", "c"],
    jsonProp: { key: "value" },
  };

  it("string passes through", () => {
    const field: Field = {
      name: "stringProp",
      kind: "input",
      inputType: "string",
      options: [],
      minimum: null,
      maximum: null,
      required: true,
      label: "String Property",
      help: "A string property",
      text: "new value",
      numericItems: false,
    };
    const newDoc = applyField(doc, field, "new value");
    expect(newDoc.stringProp).toBe("new value");
    expect(doc.stringProp).toBe("value"); // Check that the input document is not mutated
  });

  it("number '1.5' -> 1.5, '' -> null, 'abc' -> null", () => {
    const field: Field = {
      name: "numberProp",
      kind: "input",
      inputType: "number",
      options: [],
      minimum: null,
      maximum: null,
      required: true,
      label: "Number Property",
      help: "A number property",
      text: "1.5",
      numericItems: false,
    };
    let newDoc = applyField(doc, field, "1.5");
    expect(newDoc.numberProp).toBe(1.5);

    field.text = "";
    newDoc = applyField(doc, field, "");
    expect(newDoc.numberProp).toBeNull();

    field.text = "abc";
    newDoc = applyField(doc, field, "abc");
    expect(newDoc.numberProp).toBeNull();
  });

  it("boolean 'true'/'false'", () => {
    const field: Field = {
      name: "booleanProp",
      kind: "input",
      inputType: "boolean",
      options: [],
      minimum: null,
      maximum: null,
      required: true,
      label: "Boolean Property",
      help: "A boolean property",
      text: "false",
      numericItems: false,
    };
    const newDoc = applyField(doc, field, "false");
    expect(newDoc.booleanProp).toBe(false);
  });

  it("enum accepted option stored, unknown option throws", () => {
    const field: Field = {
      name: "enumProp",
      kind: "enum",
      inputType: "string",
      options: ["a", "b", "c"],
      minimum: null,
      maximum: null,
      required: true,
      label: "Enum Property",
      help: "An enum property",
      text: "b",
      numericItems: false,
    };
    let newDoc = applyField(doc, field, "b");
    expect(newDoc.enumProp).toBe("b");

    field.text = "d";
    expect(() => applyField(doc, field, "d")).toThrow('"d" is not one of the allowed options: a, b, c.');
  });

  it("scalarArray trims lines and drops empty ones", () => {
    const field: Field = {
      name: "scalarArrayProp",
      kind: "scalarArray",
      inputType: "string",
      options: [],
      minimum: null,
      maximum: null,
      required: true,
      label: "Scalar Array Property",
      help: "A scalar array property",
      text: "  a  \n\n  b  \n  c  ",
      numericItems: false,
    };
    const newDoc = applyField(doc, field, "  a  \n\n  b  \n  c  ");
    expect(newDoc.scalarArrayProp).toEqual(["a", "b", "c"]);
  });

  it("numeric scalarArray parses to numbers and throws on a non-numeric line", () => {
    const field: Field = {
      name: "scalarArrayProp",
      kind: "scalarArray",
      inputType: "string",
      options: [],
      minimum: null,
      maximum: null,
      required: true,
      label: "Scalar Array Property",
      help: "A scalar array property",
      text: "1\n2\n3",
      numericItems: true,
    };
    let newDoc = applyField(doc, field, "1\n2\n3");
    expect(newDoc.scalarArrayProp).toEqual([1, 2, 3]);

    field.text = "1\nabc\n3";
    expect(() => applyField(doc, field, "1\nabc\n3")).toThrow('"abc" is not a valid number for a numeric array item.');
  });

  it("json parses an object and throws (with the field name in the message) on invalid JSON", () => {
    const field: Field = {
      name: "jsonProp",
      kind: "json",
      inputType: "string",
      options: [],
      minimum: null,
      maximum: null,
      required: true,
      label: "JSON Property",
      help: "A JSON property",
      text: '{"key": "new value"}',
      numericItems: false,
    };
    let newDoc = applyField(doc, field, '{"key": "new value"}');
    expect(newDoc.jsonProp).toEqual({ key: "new value" });

    field.text = '{"key": "new value"';
    expect(() => applyField(doc, field, '{"key": "new value"')).toThrow('Invalid JSON for field "jsonProp":');
  });
});

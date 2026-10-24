// Tests of the pure helpers of the Import view and of the intake client functions (fetch mocked).
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, checkIntake, createIntakeDataset, previewIntake, type IntakePreview } from "./api";
import { translate } from "./i18n";
import {
  canCreate, datasetIdError, defaultMapping, defaultOptions, describeIntakeError, mappingBody, mappingComplete, verdictLevel,
} from "./intake";

const t = (key: string, params?: Record<string, string | number>) => translate("en", key, params);

const PREVIEW: IntakePreview = {
  layout: "wide", delimiter: ";", decimal: "comma", time_format: "iso", columns: ["timestamp", "LIC1.PV", "LIC1.OUT", "LIC1.MODE"],
  rows: [], n_rows_estimate: 10, tags: [],
  suggestions: { time_col: "timestamp", pv_col: "LIC1.PV", out_col: "LIC1.OUT", mode_col: "LIC1.MODE", sp_col: null, tag_pv: null },
};

afterEach(() => vi.unstubAllGlobals());

function reply(status: number, body: unknown) {
  const mock = vi.fn(() => Promise.resolve(new Response(JSON.stringify(body), { status })));
  vi.stubGlobal("fetch", mock);
  return mock;
}

describe("mapping defaults", () => {
  it("fills the form from the suggestions and leaves missing guesses empty", () => {
    const form = defaultMapping(PREVIEW);
    expect(form.time_col).toBe("timestamp");
    expect(form.pv_col).toBe("LIC1.PV");
    expect(form.sp_col).toBe("");
    expect(mappingComplete(form, "wide")).toBe(true);
    expect(defaultOptions(PREVIEW)).toEqual({ time_format: "iso", decimal: "comma", delimiter: ";" });
  });

  it("sends only the given fields of the layout in use", () => {
    expect(mappingBody(defaultMapping(PREVIEW), "wide")).toEqual({
      time_col: "timestamp", pv_col: "LIC1.PV", out_col: "LIC1.OUT", mode_col: "LIC1.MODE",
    });
  });

  it("is incomplete for a long file without tag choices", () => {
    expect(mappingComplete(defaultMapping(PREVIEW), "long")).toBe(false);
  });
});

describe("dataset id", () => {
  it.each([["run1", null], ["a-b_C", null], ["", "empty"], ["a b", "pattern"], ["../x", "pattern"], ["x".repeat(65), "pattern"], ["_soft", "underscore"]])(
    "%j -> %s", (id, expected) => expect(datasetIdError(id)).toBe(expected),
  );
});

describe("verdicts and errors", () => {
  it("maps verdicts to levels", () => {
    expect(verdictLevel("ready")).toBe("ok");
    expect(verdictLevel("usable_with_warnings")).toBe("warning");
    expect(verdictLevel("not_usable")).toBe("problem");
    expect(canCreate(null)).toBe(false);
  });

  it("translates 409, 413 and a refused record, and shows other texts", () => {
    expect(describeIntakeError(new ApiError(409, "x"), t)).toBe("A dataset with this id exists: choose another id.");
    expect(describeIntakeError(new ApiError(413, "x"), t)).toContain("25 MB");
    expect(describeIntakeError(new ApiError(422, "m", { findingCodes: ["no_out_move"] }), t)).toContain("no_out_move");
    expect(describeIntakeError(new ApiError(422, "unknown column NOPE"), t)).toContain("unknown column NOPE");
    expect(describeIntakeError(new TypeError("Failed to fetch"), t)).toContain("Failed to fetch");
  });
});

describe("intake client", () => {
  it("posts the text to preview", async () => {
    const mock = reply(200, PREVIEW);
    expect((await previewIntake("a,b")).layout).toBe("wide");
    expect(mock).toHaveBeenCalledWith("/api/intake/preview", expect.objectContaining({ method: "POST", body: JSON.stringify({ csv_text: "a,b" }) }));
  });

  it("posts text, mapping and options to check", async () => {
    const mock = reply(200, { verdict: "ready" });
    await checkIntake({ csvText: "x", mapping: { pv_col: "p" }, options: { time_format: "auto", decimal: "dot", delimiter: "," } });
    const sent = JSON.parse((mock.mock.calls[0] as unknown as [string, RequestInit])[1].body as string);
    expect(sent).toEqual({ csv_text: "x", mapping: { pv_col: "p" }, options: { time_format: "auto", decimal: "dot", delimiter: "," } });
  });

  it("creates a dataset (201) with the spec merged into the body", async () => {
    const mock = reply(201, { dataset_id: "run1", assumptions: ["UTC"], loops: [{ name: "LIC1" }] });
    const input = { csvText: "x", mapping: {}, options: { time_format: "auto" as const, decimal: "auto" as const, delimiter: "auto" } };
    const created = await createIntakeDataset(input, { dataset_id: "run1", loop_name: "LIC1", process_kind: "integrating", pv_unit: "%", out_unit: "%" });
    expect(created.loops[0].name).toBe("LIC1");
    const [url, init] = mock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/intake/dataset");
    expect(JSON.parse(init.body as string)).toMatchObject({ dataset_id: "run1", process_kind: "integrating", csv_text: "x" });
  });

  it("raises ApiError for string detail, structured detail, 409 and 413", async () => {
    reply(422, { detail: "unknown column NOPE" });
    await expect(previewIntake("x")).rejects.toMatchObject({ status: 422, message: "unknown column NOPE", findingCodes: [] });
    reply(422, { detail: { message: "the record is not usable", finding_codes: ["no_out_move"] } });
    await expect(previewIntake("x")).rejects.toMatchObject({ status: 422, message: "the record is not usable", findingCodes: ["no_out_move"] });
    reply(409, { detail: "dataset 'run1' already exists" });
    await expect(previewIntake("x")).rejects.toMatchObject({ status: 409 });
    reply(413, { detail: "the CSV is larger than 25 MB" });
    await expect(previewIntake("x")).rejects.toMatchObject({ status: 413 });
  });
});

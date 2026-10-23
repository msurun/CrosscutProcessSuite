// Tests of the plant CSV import client (see plantImport.ts): the pure form helpers and the
// fetch-based calls with the global fetch mocked. Every export of the module is covered here.
// No network is touched; replies are built as Response objects, errors as thrown Errors.
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  deletePlantUpload, importPlant, noteText, previewPlant, timezoneBody, uploadPlantFile, validDatasetId,
  type PlantNote,
} from "./plantImport";

/** A translator that knows one key per code used in the tests and echoes the key otherwise. */
const t = (key: string, params?: Record<string, string | number>) => {
  const known: Record<string, string> = {
    "plant.note.tz_iana": "offset moves from {{first}} to {{last}} h",
    "plant.note.gaps": "{{count}} gaps, period {{period}} s",
  };
  const template = known[key];
  if (template === undefined) return key;
  return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(params?.[name] ?? ""));
};

/** A note with the given code and figures, as the server would send it. */
function note(code: string, params: Record<string, unknown> = {}): PlantNote {
  return { code, text: "server text", params };
}

afterEach(() => vi.unstubAllGlobals());

/** Stub the global fetch with a reply of the given status and JSON body; return the mock. */
function reply(status: number, body: unknown) {
  const mock = vi.fn(() => Promise.resolve(new Response(status === 204 ? null : JSON.stringify(body), { status })));
  vi.stubGlobal("fetch", mock);
  return mock;
}

describe("timezoneBody", () => {
  it("uses UTC without a value", () => {
    expect(timezoneBody("utc", "")).toEqual({ kind: "utc", value: null });
  });

  it("names the Santiago zone for the site preset", () => {
    expect(timezoneBody("santiago", "")).toEqual({ kind: "iana", value: "America/Santiago" });
  });

  it("reads a negative offset with a dot", () => {
    expect(timezoneBody("offset", "-3.5")).toEqual({ kind: "offset", value: -3.5 });
  });

  it("reads an offset typed with a comma decimal separator", () => {
    expect(timezoneBody("offset", "-3,5")).toEqual({ kind: "offset", value: -3.5 });
  });

  it("rejects an empty offset", () => {
    expect(timezoneBody("offset", "  ")).toBeNull();
  });

  it("rejects an offset beyond fourteen hours", () => {
    expect(timezoneBody("offset", "15")).toBeNull();
  });

  it("rejects offset text that is not a number", () => {
    expect(timezoneBody("offset", "west")).toBeNull();
  });
});

describe("validDatasetId", () => {
  it.each([["run1"], ["a-b_C"], ["x".repeat(64)]])("accepts %j", (id) => {
    expect(validDatasetId(id)).toBe(true);
  });

  it.each([[""], ["a b"], ["../x"], ["x".repeat(65)]])("rejects %j", (id) => {
    expect(validDatasetId(id)).toBe(false);
  });
});

describe("noteText", () => {
  it("fills the first and last offsets of an IANA note", () => {
    const translated = noteText(note("tz_iana", { zone: "America/Santiago", offset_first_hours: -3, offset_last_hours: -4 }), t);
    expect(translated).toBe("offset moves from -3 to -4 h");
  });

  it("fills the count and period of a gaps note", () => {
    const translated = noteText(note("gaps", { count: 2, median_period_s: 60 }), t);
    expect(translated).toBe("2 gaps, period 60 s");
  });

  it("falls back to the server text for an unknown code", () => {
    expect(noteText(note("mystery", { rows: 3 }), t)).toBe("server text");
  });

  it("falls back to the server text when a figure is missing", () => {
    expect(noteText(note("gaps", { count: 2 }), t)).toBe("server text");
  });
});

describe("uploadPlantFile", () => {
  it("sends the raw file bytes to the role endpoint", async () => {
    const mock = reply(200, { upload_id: "u1", bytes: 3 });
    const file = new File(["a,b"], "data.csv", { type: "text/csv" });
    const result = await uploadPlantFile("data", file);
    expect(result).toEqual({ upload_id: "u1", bytes: 3 });
    const [url, init] = mock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/intake/plant/upload?role=data");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(file);
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/octet-stream");
  });

  it("throws the server message on a non-2xx reply", async () => {
    reply(413, { detail: "the data file is larger than 40 MB" });
    const file = new File(["a"], "data.csv");
    await expect(uploadPlantFile("data", file)).rejects.toThrow("the data file is larger than 40 MB");
  });
});

describe("previewPlant", () => {
  it("posts the upload ids and time zone as JSON", async () => {
    const mock = reply(200, { n_rows: 10, loops: [], notes: [] });
    const result = await previewPlant({
      data_upload: "u1",
      dictionary_upload: null,
      timezone: { kind: "utc", value: null },
    });
    expect(result.n_rows).toBe(10);
    const [url, init] = mock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/intake/plant/preview");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body as string)).toEqual({
      data_upload: "u1",
      dictionary_upload: null,
      timezone: { kind: "utc", value: null },
    });
  });

  it("throws the server message on a refused request", async () => {
    reply(422, { detail: "no data columns found" });
    const call = previewPlant({ data_upload: "u1", dictionary_upload: null, timezone: { kind: "utc", value: null } });
    await expect(call).rejects.toThrow("no data columns found");
  });
});

describe("importPlant", () => {
  it("posts the scope and dataset id with the uploads as JSON", async () => {
    const mock = reply(201, { dataset_id: "run1", loops: [], notes: [], tags_written: 0, tags_skipped: 0, test_windows: [] });
    const result = await importPlant({
      data_upload: "u1",
      dictionary_upload: "u2",
      timezone: { kind: "iana", value: "America/Santiago" },
      scope: "process",
      dataset_id: "run1",
    });
    expect(result.dataset_id).toBe("run1");
    const [url, init] = mock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/intake/plant/import");
    expect(JSON.parse(init.body as string)).toEqual({
      data_upload: "u1",
      dictionary_upload: "u2",
      timezone: { kind: "iana", value: "America/Santiago" },
      scope: "process",
      dataset_id: "run1",
    });
  });

  it("throws the server message when the dataset id exists", async () => {
    reply(409, { detail: "dataset 'run1' already exists" });
    const call = importPlant({
      data_upload: "u1", dictionary_upload: null, timezone: { kind: "utc", value: null },
      scope: "loops", dataset_id: "run1",
    });
    await expect(call).rejects.toThrow("dataset 'run1' already exists");
  });
});

describe("deletePlantUpload", () => {
  it("sends a DELETE to the upload endpoint", async () => {
    const mock = reply(204, {});
    await deletePlantUpload("u1");
    const [url, init] = mock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/intake/plant/upload/u1");
    expect(init.method).toBe("DELETE");
  });

  it("throws the server message when the upload is unknown", async () => {
    reply(404, { detail: "upload 'u1' not found" });
    await expect(deletePlantUpload("u1")).rejects.toThrow("upload 'u1' not found");
  });
});

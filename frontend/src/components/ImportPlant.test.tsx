// Component tests of the Plant import view: file inputs, preview, time zone body, dataset id
// validation, a successful import and a failing preview. fetch is mocked per route and the
// translator is the real English one from `i18n`, as in ImportPage.test.tsx.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PlantImportResult, PlantLoop, PlantPreview } from "../plantImport";
import { translate } from "../i18n";
import { ImportPlant } from "./ImportPlant";

const t = (key: string, params?: Record<string, string | number>) => translate("en", key, params);

const COMPLETE_LOOP: PlantLoop = {
  id: "lic1", name: "LIC1", process_kind: "self_regulating",
  pv: "LIC1.PV", sp: "LIC1.SP", out: "LIC1.OUT", mode: "LIC1.MODE", feedback: null, valves: [],
  unit: "m", cell: "Cell 1", complete: true, missing: [],
};

const INCOMPLETE_LOOP: PlantLoop = {
  id: "fic2", name: "FIC2", process_kind: "integrating",
  pv: "FIC2.PV", sp: null, out: "FIC2.OUT", mode: null, feedback: null, valves: [],
  unit: "m3/h", cell: "Cell 2", complete: false, missing: ["sp", "mode"],
};

const PREVIEW: PlantPreview = {
  n_rows: 2400, n_columns: 12,
  start_local: "2026-03-01 06:00:00", end_local: "2026-03-01 07:20:00",
  start_utc: "2026-03-01T09:00:00Z", end_utc: "2026-03-01T10:20:00Z",
  period_s: 2, n_gaps: 1,
  gaps: [{ start_utc: "2026-03-01T09:10:00Z", end_utc: "2026-03-01T09:12:00Z", seconds: 120 }],
  loops: [COMPLETE_LOOP, INCOMPLETE_LOOP],
  skipped: { count: 0, reason: "" },
  test_windows: [
    { label: "W1", start_utc: "2026-03-01T09:20:00Z", end_utc: "2026-03-01T09:50:00Z", rows: 900 },
  ],
  notes: [{ code: "read_plant", text: "Read 2400 rows and 12 columns", params: { rows: 2400, columns: 12 } }],
};

const IMPORT_RESULT: PlantImportResult = {
  dataset_id: "run1", loops: [COMPLETE_LOOP, INCOMPLETE_LOOP], notes: PREVIEW.notes,
  tags_written: 18, tags_skipped: 2, test_windows: PREVIEW.test_windows,
};

type Routes = Record<string, { status?: number; body: unknown }>;

/** fetch mock: JSON routes by path; any `.../upload/<id>` DELETE answers 204. */
function respond(routes: Routes) {
  const mock = vi.fn((url: string, init?: RequestInit) => {
    if (init?.method === "DELETE" && url.startsWith("/api/intake/plant/upload/")) {
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    const route = routes[url];
    if (route === undefined) return Promise.reject(new Error(`unexpected ${url}`));
    return Promise.resolve(new Response(JSON.stringify(route.body), { status: route.status ?? 200 }));
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

/** Body of the first call to `path` in the given HTTP method. */
function sentBody(mock: ReturnType<typeof respond>, path: string, method: string): unknown {
  const call = mock.mock.calls.find(([url, init]) => url === path && init?.method === method);
  return JSON.parse(String(call?.[1]?.body));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const renderPage = (onOpen = vi.fn(), onCreated = vi.fn()) =>
  render(<ImportPlant onCreated={onCreated} onOpen={onOpen} t={t} />);

/** Choose the data file and run the preview, waiting for the loops table. */
async function chooseFileAndPreview(dataName = "plant.csv") {
  const file = new File(["a;b\n1;2"], dataName, { type: "text/csv" });
  fireEvent.change(screen.getByLabelText("Data file (CSV, wide layout)"), { target: { files: [file] } });
  fireEvent.click(screen.getByRole("button", { name: "Read and preview" }));
  await screen.findByText("LIC1");
}

function chooseDataFile() {
  const file = new File(["a;b\n1;2"], "plant.csv", { type: "text/csv" });
  fireEvent.change(screen.getByLabelText("Data file (CSV, wide layout)"), { target: { files: [file] } });
}

describe("initial render", () => {
  it("shows the data and dictionary inputs with the preview button disabled", () => {
    renderPage();
    expect(screen.getByLabelText("Data file (CSV, wide layout)")).toBeInTheDocument();
    expect(screen.getByLabelText("Dictionary file (optional)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Read and preview" })).toBeDisabled();
  });

  it("enables the preview button once a data file is chosen", () => {
    renderPage();
    chooseDataFile();
    expect(screen.getByRole("button", { name: "Read and preview" })).toBeEnabled();
  });
});

describe("preview", () => {
  it("lists the loops, the missing roles, the test windows and the notes", async () => {
    respond({
      "/api/intake/plant/upload?role=data": { body: { upload_id: "up-data", bytes: 8 } },
      "/api/intake/plant/preview": { body: PREVIEW },
    });
    renderPage();
    await chooseFileAndPreview();
    expect(screen.getByText("LIC1")).toBeInTheDocument();
    expect(screen.getByText("Complete")).toBeInTheDocument();
    expect(screen.getByText("FIC2")).toBeInTheDocument();
    expect(screen.getByText(/Missing roles: sp, mode/)).toBeInTheDocument();
    expect(screen.getByText("W1")).toBeInTheDocument();
    expect(screen.getByText("Read plant data: 2400 rows, 12 columns")).toBeInTheDocument();
  });

  it("sends the IANA Santiago time zone when the preset is Santiago", async () => {
    const mock = respond({
      "/api/intake/plant/upload?role=data": { body: { upload_id: "up-data", bytes: 8 } },
      "/api/intake/plant/preview": { body: PREVIEW },
    });
    renderPage();
    fireEvent.change(screen.getByLabelText("Time zone"), { target: { value: "santiago" } });
    await chooseFileAndPreview();
    const timezone = (sentBody(mock, "/api/intake/plant/preview", "POST") as { timezone: unknown }).timezone;
    expect(timezone).toEqual({ kind: "iana", value: "America/Santiago" });
  });

  it("sends the offset as a number when the preset is offset and the text is -3", async () => {
    const mock = respond({
      "/api/intake/plant/upload?role=data": { body: { upload_id: "up-data", bytes: 8 } },
      "/api/intake/plant/preview": { body: PREVIEW },
    });
    renderPage();
    fireEvent.change(screen.getByLabelText("Time zone"), { target: { value: "offset" } });
    fireEvent.change(screen.getByLabelText("Offset hours"), { target: { value: "-3" } });
    await chooseFileAndPreview();
    const timezone = (sentBody(mock, "/api/intake/plant/preview", "POST") as { timezone: unknown }).timezone;
    expect(timezone).toEqual({ kind: "offset", value: -3 });
  });

  it("shows the server message in an alert when the preview fails", async () => {
    respond({
      "/api/intake/plant/upload?role=data": { body: { upload_id: "up-data", bytes: 8 } },
      "/api/intake/plant/preview": { status: 422, body: { detail: "no timestamp column found" } },
    });
    renderPage();
    chooseDataFile();
    fireEvent.click(screen.getByRole("button", { name: "Read and preview" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("no timestamp column found");
  });
});

describe("dataset id", () => {
  it("shows the invalid message and disables Import for an id with a space", async () => {
    respond({
      "/api/intake/plant/upload?role=data": { body: { upload_id: "up-data", bytes: 8 } },
      "/api/intake/plant/preview": { body: PREVIEW },
    });
    renderPage();
    await chooseFileAndPreview();
    fireEvent.change(screen.getByLabelText("Dataset ID"), { target: { value: "bad id" } });
    expect(screen.getByRole("alert")).toHaveTextContent("Invalid dataset ID");
    expect(screen.getByRole("button", { name: "Import" })).toBeDisabled();
  });
});

describe("import", () => {
  it("reports what was written and opens each loop in Tuning", async () => {
    const mock = respond({
      "/api/intake/plant/upload?role=data": { body: { upload_id: "up-data", bytes: 8 } },
      "/api/intake/plant/preview": { body: PREVIEW },
      "/api/intake/plant/import": { body: IMPORT_RESULT },
    });
    const onOpen = vi.fn();
    const onCreated = vi.fn();
    renderPage(onOpen, onCreated);
    await chooseFileAndPreview();
    fireEvent.change(screen.getByLabelText("Dataset ID"), { target: { value: "run1" } });
    fireEvent.click(screen.getByRole("button", { name: "Import" }));
    await screen.findByTestId("plant-done");
    expect(screen.getByRole("status")).toHaveTextContent("Written: 18, Skipped: 2");
    expect(sentBody(mock, "/api/intake/plant/import", "POST")).toMatchObject({ dataset_id: "run1" });
    expect(onCreated).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Open loop FIC2" }));
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith("run1", "fic2"));
  });
});

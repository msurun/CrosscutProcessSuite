// Component tests of the Import view: notes, preview with the mapping pre-filled from the
// suggestions, verdict rendering, dataset id validation, the disabled create button, the error
// texts (409, 422) and the way into the Tuning view. fetch is mocked, TrendPane is stubbed.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { IntakeCheck, IntakePreview } from "../api";
import { translate } from "../i18n";
import { ImportPage } from "./ImportPage";

vi.mock("./TrendPane", () => ({ TrendPane: () => null }));

const t = (key: string, params?: Record<string, string | number>) => translate("en", key, params);

const PREVIEW: IntakePreview = {
  layout: "wide", delimiter: ";", decimal: "comma", time_format: "iso", columns: ["timestamp", "LIC1.PV", "LIC1.OUT", "LIC1.MODE"],
  rows: [["2026-03-01T06:00:00", "40,0", "50,0", "MAN"]], n_rows_estimate: 2400, tags: [],
  suggestions: { time_col: "timestamp", pv_col: "LIC1.PV", out_col: "LIC1.OUT", mode_col: "LIC1.MODE", sp_col: null },
};

function check(verdict: IntakeCheck["verdict"]): IntakeCheck {
  const blocked = verdict === "not_usable";
  return {
    n: 2400, duration_s: 4800, dt_median_s: 2, dt_max_s: 2, uneven_sampling: false, out_range: 6, n_out_moves: 2, first_move_s: 1800,
    lead_share: 0.375, post_last_move_s: 900, pv_range: 12, manual_share: 1, verdict,
    findings: blocked ? [{ code: "no_out_move", text: "OUT never moved", what_to_do: "Record again with a step", blocking: true }] : [],
    dry_run: blocked ? null : { verdict: "ok", reasons: [], slope_per_s: 0.002, delay_s: 6, delay_lower_s: 4, delay_upper_s: 8, r_squared: 0.99, error: "" },
    read_as: ["times read as UTC"], sample: { t_s: [0, 2, 4], pv: [1, 2, 3], out: [50, 50, 56] },
  };
}

type Routes = Record<string, { status?: number; body: unknown }>;

function respond(routes: Routes) {
  const mock = vi.fn((url: string) => {
    const route = routes[url];
    if (route === undefined) return Promise.reject(new Error(`unexpected ${url}`));
    return Promise.resolve(new Response(JSON.stringify(route.body), { status: route.status ?? 200 }));
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function pasteAndPreview() {
  fireEvent.change(screen.getByLabelText("Or paste the CSV text here"), { target: { value: "timestamp;LIC1.PV\n1;2" } });
  fireEvent.click(screen.getByRole("button", { name: "Use the pasted text" }));
  await screen.findByText("2. Check the preview and the columns");
}

async function runCheck() {
  fireEvent.click(screen.getByRole("button", { name: "3. Check the record" }));
  await screen.findByTestId("import-result");
}

const renderPage = (onOpen = vi.fn(), onCreated = vi.fn()) => render(<ImportPage onCreated={onCreated} onOpen={onOpen} t={t} />);

describe("notes and preview", () => {
  it("shows both notes with role=note", () => {
    renderPage();
    const notes = screen.getAllByRole("note");
    expect(notes[0]).toHaveTextContent("Nothing is sent to the plant.");
    expect(notes[1]).toHaveTextContent("Times without a time zone are read as UTC");
  });

  it("pre-fills the mapping and the format selects from the preview", async () => {
    respond({ "/api/intake/preview": { body: PREVIEW } });
    renderPage();
    await pasteAndPreview();
    expect(screen.getByLabelText("Process variable (level)")).toHaveValue("LIC1.PV");
    expect(screen.getByLabelText("Controller output (valve)")).toHaveValue("LIC1.OUT");
    expect(screen.getByLabelText("Setpoint (optional)")).toHaveValue("");
    expect(screen.getByLabelText("Column separator")).toHaveValue(";");
    expect(screen.getByLabelText("Decimal mark")).toHaveValue("comma");
    expect(screen.getByTestId("import-source")).toHaveTextContent("pasted text");
  });

  it("shows a translated message when the file is refused with 413", async () => {
    respond({ "/api/intake/preview": { status: 413, body: { detail: "the CSV is larger than 25 MB" } } });
    renderPage();
    fireEvent.change(screen.getByLabelText("Or paste the CSV text here"), { target: { value: "a;b" } });
    fireEvent.click(screen.getByRole("button", { name: "Use the pasted text" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("larger than 25 MB. Export a shorter record.");
  });
});

describe("check and create", () => {
  it("renders the verdict, numbers and the dry run for a ready record", async () => {
    respond({ "/api/intake/preview": { body: PREVIEW }, "/api/intake/check": { body: check("ready") } });
    renderPage();
    await pasteAndPreview();
    await runCheck();
    expect(screen.getByRole("status")).toHaveTextContent("Ready");
    expect(screen.getByText("Record length").nextSibling).toHaveTextContent("80.0 min");
    expect(screen.getByText("Quiet lead share").nextSibling).toHaveTextContent("37.5 %");
    expect(screen.getByText("(range 4 to 8 s)", { exact: false })).toBeInTheDocument();
    expect(screen.getByText(/upper bound of the dead-time range/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create dataset" })).toBeDisabled();
  });

  it("marks blocking findings and keeps Create disabled for a not usable record", async () => {
    respond({ "/api/intake/preview": { body: PREVIEW }, "/api/intake/check": { body: check("not_usable") } });
    renderPage();
    await pasteAndPreview();
    await runCheck();
    expect(screen.getByRole("status")).toHaveTextContent("Not usable");
    expect(screen.getByText("blocking")).toBeInTheDocument();
    expect(screen.getByText("What to do: Record again with a step")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Dataset id"), { target: { value: "run1" } });
    expect(screen.getByRole("button", { name: "Create dataset" })).toBeDisabled();
  });

  it("validates the dataset id while typing and enables Create only for a valid id", async () => {
    respond({ "/api/intake/preview": { body: PREVIEW }, "/api/intake/check": { body: check("usable_with_warnings") } });
    renderPage();
    await pasteAndPreview();
    await runCheck();
    const id = screen.getByLabelText("Dataset id");
    const create = screen.getByRole("button", { name: "Create dataset" });
    fireEvent.change(id, { target: { value: "bad id" } });
    expect(screen.getByRole("alert")).toHaveTextContent("Use only letters, digits");
    expect(create).toBeDisabled();
    fireEvent.change(id, { target: { value: "_hidden" } });
    expect(screen.getByRole("alert")).toHaveTextContent("must not start with _");
    fireEvent.change(id, { target: { value: "run1" } });
    expect(create).toBeEnabled();
  });

  it("explains a 409 and, after success, lists the assumptions and opens Tuning", async () => {
    const created = { dataset_id: "run1", assumptions: ["resampled to 2 s"], loops: [{ name: "LIC1" }] };
    const routes: Routes = {
      "/api/intake/preview": { body: PREVIEW }, "/api/intake/check": { body: check("ready") },
      "/api/intake/dataset": { status: 409, body: { detail: "dataset 'run1' already exists" } },
    };
    respond(routes);
    const onOpen = vi.fn();
    const onCreated = vi.fn();
    renderPage(onOpen, onCreated);
    await pasteAndPreview();
    await runCheck();
    fireEvent.change(screen.getByLabelText("Dataset id"), { target: { value: "run1" } });
    fireEvent.click(screen.getByRole("button", { name: "Create dataset" }));
    expect(await screen.findByText("A dataset with this id exists: choose another id.")).toBeInTheDocument();
    routes["/api/intake/dataset"] = { status: 201, body: created };
    fireEvent.click(screen.getByRole("button", { name: "Create dataset" }));
    await screen.findByTestId("import-done");
    expect(screen.getByText("resampled to 2 s")).toBeInTheDocument();
    expect(onCreated).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Open in Tuning" }));
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith("run1", "LIC1"));
  });
});

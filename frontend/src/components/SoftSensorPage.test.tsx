// Component tests of the Soft sensor page: notes, empty state with Load example, lab upload
// validation, fit validation, model summary, run result (validity counts, flags rule, scores) and
// the error / not-fitted / stale / unknown-tag states.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SoftSensorModelSummary, SoftSensorRun } from "../api";
import { translate } from "../i18n";
import { SoftSensorFit } from "./SoftSensorFit";
import { SoftSensorLab } from "./SoftSensorLab";
import { SoftSensorModel } from "./SoftSensorModel";
import { SoftSensorNotes, SoftSensorPage } from "./SoftSensorPage";
import { SoftSensorValidityView } from "./SoftSensorValidity";

vi.mock("./TrendPane", () => ({ TrendPane: () => null }));

const t = (key: string, params?: Record<string, string | number>) => translate("en", key, params);
const ID = "mill_circuit_pls";
const BASE = `/api/softsensor/${ID}`;
const DATASET = "ds";

const MODEL: SoftSensorModelSummary = {
  n_components: 3, cv_rmse: [4, 2, 1.5], chosen_components: 2, cv_sigma: 0.5, n_train: 36, domain_rows: 240,
  r2_train: 0.91234, sha256: "abcdef0123456789".repeat(4), window: { start_s: 0, end_s: 16200 }, dataset_id: DATASET,
  created_utc: "2026-10-23T00:00:00+00:00",
};
const CONFIG = {
  schema_version: "1.0.0", id: ID, target_tag: "lab.quality", input_tags: ["sim.mc.mill_power"], lab_delay_s: 3600, mode: "advisory",
};
const RUN: SoftSensorRun = {
  series: {
    t_s: [0, 60, 120, 180], estimate: [null, 11, 12, 13], corrected: [null, null, 12, 13],
    bias: [null, 0, 0.1, 0.2], drift: [false, false, true, true], validity: ["missing_input", "ok", "extrapolation", "out_of_range"],
  },
  validity_counts: { ok: 1, missing_input: 1, out_of_range: 1, extrapolation: 1 },
  drift_episodes: [{ start_s: 120, end_s: 180 }],
  lab_points: [{ t_s: 120, value: 12.5 }],
  n_lab_used: 1,
  latest: { t_s: 180, estimate: 13, corrected: 13, bias: 0.2, drift: true, validity: "out_of_range" },
};

type Routes = Record<string, { status?: number; body: unknown }>;

/** Stubs fetch with answers by "METHOD url"; an unlisted request fails the test. */
function respond(routes: Routes) {
  const mock = vi.fn((url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${url}`;
    const route = routes[key];
    if (route === undefined) return Promise.reject(new Error(`unexpected ${key}`));
    return Promise.resolve(new Response(JSON.stringify(route.body), { status: route.status ?? 200 }));
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

const storedRoutes = (extra: Routes = {}): Routes => ({
  "GET /api/softsensor": { body: [ID] },
  [`GET ${BASE}`]: { body: CONFIG },
  [`GET ${BASE}/lab`]: { status: 404, body: { detail: `no lab results uploaded: ${ID}` } },
  [`GET ${BASE}/model`]: { status: 404, body: { detail: `model not fitted: ${ID}` } },
  ...extra,
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("notes", () => {
  it("shows both notes with role=note", () => {
    render(<SoftSensorNotes t={t} />);
    const notes = screen.getAllByRole("note");
    expect(notes[0]).toHaveTextContent("Advisory only: nothing is written to the plant.");
    expect(notes[1]).toHaveTextContent("it has not been validated on a real plant.");
    expect(notes[1]).toHaveTextContent("Do not use it where an extrapolation or out-of-range flag is shown.");
  });
});

describe("page states", () => {
  it("offers Load example when nothing is configured and saves the bundled config", async () => {
    respond({ "GET /api/softsensor": { body: [] } });
    render(<SoftSensorPage datasetId={DATASET} recordHours={6} startUtc="2026-01-01T00:00:00Z" t={t} />);
    expect(await screen.findByTestId("soft-empty")).toBeInTheDocument();
    respond(storedRoutes({ [`PUT ${BASE}`]: { body: CONFIG } }));
    fireEvent.click(screen.getByRole("button", { name: "Load example" }));
    expect(await screen.findByLabelText("Soft sensor")).toHaveValue(ID);
    expect(await screen.findByTestId("soft-no-model")).toBeInTheDocument();
    expect(screen.getByTestId("soft-lab-none")).toBeInTheDocument();
    expect(screen.getByTestId("soft-fit-needs-lab")).toBeInTheDocument();
  });

  it("shows the API error text when the list cannot be read", async () => {
    respond({ "GET /api/softsensor": { status: 500, body: { detail: "boom" } } });
    render(<SoftSensorPage datasetId={DATASET} recordHours={6} startUtc="" t={t} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
  });
});

describe("lab upload", () => {
  const lab = { value: null, loaded: true, error: null, set: vi.fn() };

  it("refuses an empty text and a header without the columns before sending", () => {
    const mock = respond({});
    render(<SoftSensorLab sid={ID} lab={lab} originDefault="" t={t} />);
    const box = screen.getByLabelText("Lab results (CSV text)");
    fireEvent.change(box, { target: { value: "time,val\n1,2" } });
    fireEvent.click(screen.getByRole("button", { name: "Upload lab results" }));
    expect(screen.getByRole("alert")).toHaveTextContent("must name the columns sample_time and value");
    expect(mock).not.toHaveBeenCalled();
  });

  it("shows the API message of a bad line", async () => {
    respond({ [`POST ${BASE}/lab`]: { status: 422, body: { detail: "line 3: bad value 'x'" } } });
    render(<SoftSensorLab sid={ID} lab={lab} originDefault="" t={t} />);
    fireEvent.change(screen.getByLabelText("Lab results (CSV text)"), { target: { value: "sample_time,value\n0,1\n1,x" } });
    fireEvent.click(screen.getByRole("button", { name: "Upload lab results" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Problem in the lab CSV: line 3: bad value 'x'");
  });

  it("sends the origin and hands the stored summary on", async () => {
    const summary = { count: 2, first_s: 0, last_s: 3600, rows: [] };
    const set = vi.fn();
    const mock = respond({ [`POST ${BASE}/lab`]: { body: summary } });
    render(<SoftSensorLab sid={ID} lab={{ ...lab, set }} originDefault="2026-01-01T00:00:00Z" t={t} />);
    fireEvent.change(screen.getByLabelText("Lab results (CSV text)"), { target: { value: "sample_time,value\n0,1\n3600,2" } });
    fireEvent.click(screen.getByRole("button", { name: "Upload lab results" }));
    await waitFor(() => expect(set).toHaveBeenCalledWith(summary));
    const init = mock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(String(init.body))).toEqual({ csv_text: "sample_time,value\n0,1\n3600,2", origin_iso: "2026-01-01T00:00:00Z" });
  });

  it("shows count and first and last time of what is stored", () => {
    const stored = { ...lab, value: { count: 72, first_s: 0, last_s: 21300, rows: [] } };
    render(<SoftSensorLab sid={ID} lab={stored} originDefault="" t={t} />);
    expect(screen.getByTestId("soft-lab-stored")).toHaveTextContent("Stored: 72 results, first at 0.00 h, last at 5.92 h");
  });
});

describe("fit form", () => {
  const props = { datasetId: DATASET, sensorId: ID, recordHours: 6, hasLab: true, labDelayS: 3600, t, onFitted: vi.fn() };

  it("explains that only results available before the train end are used", () => {
    render(<SoftSensorFit {...props} />);
    expect(screen.getByText(/AVAILABLE before the train end/)).toBeInTheDocument();
    expect(screen.getByLabelText("Train end (h)")).toHaveValue("4.5");
  });

  it("blocks a train end beyond the record and a non-number", () => {
    render(<SoftSensorFit {...props} />);
    const field = screen.getByLabelText("Train end (h)");
    fireEvent.change(field, { target: { value: "9" } });
    expect(screen.getByRole("alert")).toHaveTextContent("after the end of the record (6.00 h)");
    expect(screen.getByRole("button", { name: "Fit model" })).toBeDisabled();
    fireEvent.change(field, { target: { value: "abc" } });
    expect(screen.getByRole("alert")).toHaveTextContent("as a number of hours");
  });

  it("sends the train end in seconds and reports the model", async () => {
    const onFitted = vi.fn();
    const mock = respond({ [`POST /api/datasets/${DATASET}/softsensor/${ID}/fit`]: { body: MODEL } });
    render(<SoftSensorFit {...props} onFitted={onFitted} />);
    fireEvent.click(screen.getByRole("button", { name: "Fit model" }));
    await waitFor(() => expect(onFitted).toHaveBeenCalledWith(MODEL));
    expect(JSON.parse(String((mock.mock.calls[0][1] as RequestInit).body))).toEqual({ train_end_s: 16200 });
  });

  it("needs lab results before it can fit", () => {
    render(<SoftSensorFit {...props} hasLab={false} />);
    expect(screen.getByRole("button", { name: "Fit model" })).toBeDisabled();
    expect(screen.getByTestId("soft-fit-needs-lab")).toBeInTheDocument();
  });

  it("shows a translated message for a fit problem with the API detail", async () => {
    respond({ [`POST /api/datasets/${DATASET}/softsensor/${ID}/fit`]: { status: 422, body: { detail: "too few valid rows: 3 < 10" } } });
    render(<SoftSensorFit {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Fit model" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be fitted: too few valid rows: 3 < 10");
  });
});

describe("model summary", () => {
  it("shows the chosen components, the CV bars as text, sigma, rows, R2 and the short hash", () => {
    render(<SoftSensorModel model={MODEL} t={t} />);
    const bars = screen.getByRole("list", { name: "Cross-validated RMSE by number of components" });
    const items = bars.querySelectorAll("li");
    expect(items).toHaveLength(3);
    expect(items[1]).toHaveTextContent("Components: 2 (chosen)2");
    expect(screen.getByText("0.912")).toBeInTheDocument();
    expect(screen.getByText("36")).toBeInTheDocument();
    expect(screen.getByText("240")).toBeInTheDocument();
    expect(screen.getByText("Model hash (SHA-256): abcdef01")).toBeInTheDocument();
  });

  it("says when no model is fitted", () => {
    render(<SoftSensorModel model={null} t={t} />);
    expect(screen.getByTestId("soft-no-model")).toHaveTextContent("No model is fitted yet");
  });
});

describe("validity counts", () => {
  it("lists each class with its count, percentage and explanation", () => {
    render(<SoftSensorValidityView counts={{ ok: 6, missing_input: 2, out_of_range: 1, extrapolation: 1 }} t={t} />);
    expect(screen.getByTestId("validity-ok")).toHaveTextContent("ok: 6 (60.0 %)");
    expect(screen.getByTestId("validity-ok")).toHaveTextContent("inside the range");
    expect(screen.getByTestId("validity-missing_input")).toHaveTextContent("missing input: 2 (20.0 %)");
    expect(screen.getByTestId("validity-out_of_range")).toHaveTextContent("out of range: 1 (10.0 %) - do not use these estimates");
    expect(screen.getByTestId("validity-extrapolation")).toHaveTextContent("extrapolation: 1 (10.0 %) - do not use these estimates");
  });

  it("does not warn about classes with no estimates", () => {
    render(<SoftSensorValidityView counts={{ ok: 3, missing_input: 0, out_of_range: 0, extrapolation: 0 }} t={t} />);
    expect(screen.queryByText(/do not use these estimates/)).toBeNull();
  });
});

describe("run on the page", () => {
  const model = { body: MODEL };
  const labs = { body: { count: 1, first_s: 0, last_s: 120, rows: [{ t_s: 0, value: 10 }, { t_s: 120, value: 12.5 }] } };

  async function openRun(run: { status?: number; body: unknown }) {
    respond(storedRoutes({
      [`GET ${BASE}/lab`]: labs,
      [`GET ${BASE}/model`]: model,
      [`POST /api/datasets/${DATASET}/softsensor/${ID}/run`]: run,
    }));
    render(<SoftSensorPage datasetId={DATASET} recordHours={6} startUtc="" t={t} />);
    fireEvent.click(await screen.findByRole("button", { name: "Run" }));
  }

  it("shows validity counts, the flags rule, the scores and the drift episode", async () => {
    await openRun({ body: RUN });
    expect(await screen.findByTestId("soft-result")).toBeInTheDocument();
    expect(screen.getByTestId("validity-extrapolation")).toHaveTextContent("extrapolation: 1");
    expect(screen.getByTestId("soft-flagged")).toBeInTheDocument();
    expect(screen.getByText(/Do not use the estimate where an extrapolation or out-of-range flag is shown/)).toBeInTheDocument();
    expect(screen.getByTestId("soft-scores")).toHaveTextContent("Laboratory results used for bias tracking: 1");
    expect(screen.getByTestId("soft-drift")).toHaveTextContent("beyond ±1");
    expect(screen.getByTestId("soft-drift")).toHaveTextContent("Drift episodes: 1");
  });

  it("explains a stale model", async () => {
    await openRun({ status: 422, body: { detail: "input_tags: model is stale, fit it again" } });
    expect(await screen.findByRole("alert")).toHaveTextContent("The model is stale");
  });

  it("names the unknown tag", async () => {
    await openRun({ status: 422, body: { detail: "unknown tags: ['sim.mc.nope']" } });
    expect(await screen.findByRole("alert")).toHaveTextContent("The dataset has no such tag: unknown tags: ['sim.mc.nope']");
  });
});

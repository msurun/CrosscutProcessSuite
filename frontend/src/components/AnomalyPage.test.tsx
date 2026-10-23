// Component tests of the Anomalies page: notes, empty state with Load example, contribution bars,
// events table, window validation in the fit form and the error / not-fitted states.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AnomalyEvent, AnomalyModelSummary } from "../api";
import { translate } from "../i18n";
import { AnomalyContributions } from "./AnomalyContributions";
import { AnomalyEventsTable } from "./AnomalyEvents";
import { AnomalyFit } from "./AnomalyFit";
import { AnomalyModel } from "./AnomalyModel";
import { AnomalyNotes, AnomalyPage } from "./AnomalyPage";

vi.mock("./TrendPane", () => ({ TrendPane: () => null }));

const t = (key: string, params?: Record<string, string | number>) => translate("en", key, params);

const EVENT: AnomalyEvent = {
  start_index: 10, end_index: 20, start_s: 3600, end_s: 4800, closed: false, peak_t2: 30, peak_spe: 5, peak_index: 15,
  top_spe_tags: ["sim.mc.p80"], top_t2_tags: ["sim.mc.p80"], exceeded: "spe", n_samples: 21,
  contributions: { spe: { "sim.mc.p80": 0.7, "sim.mc.mill_power": 0.3 }, t2: { "sim.mc.p80": 0.4, "sim.mc.mill_power": 0.6 } },
};
const MODEL: AnomalyModelSummary = {
  k: 2, n_train: 240, explained_variance: [0.6, 0.3], cumulative_variance: [0.6, 0.9], t2_limit: 9.21, spe_limit: 4.5,
  sha256: "abcdef0123456789".repeat(4), window: { start_s: 0, end_s: 14400 }, dataset_id: "ds", created_utc: "2026-10-22T00:00:00+00:00",
};

function respond(routes: Record<string, { status?: number; body: unknown }>) {
  const mock = vi.fn((url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${url}`;
    const route = routes[key];
    if (route === undefined) return Promise.reject(new Error(`unexpected ${key}`));
    return Promise.resolve(new Response(JSON.stringify(route.body), { status: route.status ?? 200 }));
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("notes", () => {
  it("shows both notes with role=note", () => {
    render(<AnomalyNotes t={t} />);
    const notes = screen.getAllByRole("note");
    expect(notes[0]).toHaveTextContent("Advisory only: nothing is written to the plant.");
    expect(notes[1]).toHaveTextContent("tested on simulated data only; expect to tune the number of consecutive samples on real data.");
  });
});

describe("contribution bars", () => {
  it("shows tag names and the share as text, largest first", () => {
    render(<AnomalyContributions event={EVENT} number={1} t={t} />);
    const spe = screen.getByRole("list", { name: "SPE share" });
    const items = spe.querySelectorAll("li");
    expect(items[0]).toHaveTextContent("sim.mc.p80");
    expect(items[0]).toHaveTextContent("70.0 %");
    expect(screen.getByRole("list", { name: "T² share" }).querySelector("li")).toHaveTextContent("sim.mc.mill_power60.0 %");
  });
});

describe("events table", () => {
  it("lists start, duration, ratios, exceeded statistic and open state; selects on click", () => {
    const onSelect = vi.fn();
    render(<AnomalyEventsTable events={[EVENT]} t2Limit={15} speLimit={2.5} selected={0} onSelect={onSelect} t={t} />);
    const cells = screen.getAllByRole("cell").map((cell) => cell.textContent);
    expect(cells).toEqual(["1.00", "1.33", "20", "2.00", "2.00", "SPE", "still open"]);
    fireEvent.click(screen.getByRole("button", { name: "Show contributions of event 1" }));
    expect(onSelect).toHaveBeenCalledWith(0);
  });
  it("says there are no events", () => {
    render(<AnomalyEventsTable events={[]} t2Limit={1} speLimit={1} selected={0} onSelect={vi.fn()} t={t} />);
    expect(screen.getByText("No events in this window.")).toBeInTheDocument();
  });
});

describe("model summary", () => {
  it("shows k, limits, cumulative variance as text and the short hash", () => {
    render(<AnomalyModel model={MODEL} t={t} />);
    expect(screen.getByText("90.0 %")).toBeInTheDocument();
    expect(screen.getByText("9.21")).toBeInTheDocument();
    expect(screen.getByText(/abcdef01$/)).toBeInTheDocument();
  });
  it("shows the not-fitted text", () => {
    render(<AnomalyModel model={null} t={t} />);
    expect(screen.getByTestId("anomaly-no-model")).toBeInTheDocument();
  });
});

describe("fit form", () => {
  it("defaults to the first half of the record and blocks an invalid window", () => {
    render(<AnomalyFit datasetId="ds" detectorId="mc" recordHours={8} t={t} onFitted={vi.fn()} />);
    expect(screen.getByLabelText("Window end (h)")).toHaveValue("4");
    fireEvent.change(screen.getByLabelText("Window end (h)"), { target: { value: "0" } });
    expect(screen.getByRole("alert")).toHaveTextContent("The end must be after the start.");
    expect(screen.getByRole("button", { name: "Fit model" })).toBeDisabled();
  });
  it("shows the translated message when the API says a tag is unknown", async () => {
    respond({ "POST /api/datasets/ds/anomaly/mc/fit": { status: 404, body: { detail: "unknown tags: ['x']" } } });
    render(<AnomalyFit datasetId="ds" detectorId="mc" recordHours={8} t={t} onFitted={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Fit model" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The dataset has no such tag: unknown tags: ['x']");
  });
  it("hands the model over after a fit", async () => {
    respond({ "POST /api/datasets/ds/anomaly/mc/fit": { body: MODEL } });
    const onFitted = vi.fn();
    render(<AnomalyFit datasetId="ds" detectorId="mc" recordHours={8} t={t} onFitted={onFitted} />);
    fireEvent.click(screen.getByRole("button", { name: "Fit model" }));
    await waitFor(() => expect(onFitted).toHaveBeenCalledWith(MODEL));
  });
});

describe("page", () => {
  it("offers Load example when no detector exists and saves the bundled config", async () => {
    const mock = respond({
      "GET /api/anomaly": { body: [] },
      "PUT /api/anomaly/mill_circuit_pca": { body: {} },
    });
    render(<AnomalyPage datasetId="ds" recordHours={8} t={t} />);
    fireEvent.click(await screen.findByRole("button", { name: "Load example" }));
    await waitFor(() => expect(mock.mock.calls.some(([url, init]) => url === "/api/anomaly/mill_circuit_pca" && init?.method === "PUT")).toBe(true));
  });
  it("shows the config as advisory only and the not-fitted state", async () => {
    respond({
      "GET /api/anomaly": { body: ["mc"] },
      "GET /api/anomaly/mc": { body: { schema_version: "1.0.0", id: "mc", tags: ["a", "b", "c"], mode: "advisory" } },
      "GET /api/anomaly/mc/model": { status: 404, body: { detail: "model not fitted: mc" } },
    });
    render(<AnomalyPage datasetId="ds" recordHours={8} t={t} />);
    expect(await screen.findByTestId("anomaly-no-model")).toBeInTheDocument();
    expect(screen.getAllByText("advisory only").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Scan" })).toBeNull();
  });
});

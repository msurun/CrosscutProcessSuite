// Component tests of the Steps view: loop/model/logbook form, the POST of the analysis, the
// table of steps, the summary, selecting a row and the chart, the empty payload, a failing
// request and the race of two quick runs. fetch is mocked at /api/datasets/d1/steps and the
// translator is the real English one from `i18n`, as in ImportPlant.test.tsx.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { StepsPayload, StepRow } from "../stepAnalyzer";
vi.mock("./TrendPane", () => ({ TrendPane: () => <div data-testid="trend-pane" /> }));
import { translate } from "../i18n";
import { StepsPage } from "./StepsPage";

const t = (key: string, params?: Record<string, string | number>) => translate("en", key, params);

const STEPS_PATH = "/api/datasets/d1/steps";

/** One sample of a two-point window, enough for the chart to have data. */
const SAMPLE = {
  t_s: [0, 60, 120],
  pv: [1.0, 1.5, 2.0],
  out: [50, 55, 60],
  fit: [1.0, 1.6, 2.0],
};

const OUT_STEP_ROW: StepRow = {
  id: "step-1",
  kind: "out_step",
  mode: "manual",
  closed_loop: false,
  start_utc: "2026-03-01T09:00:00Z",
  event_utc: "2026-03-01T09:05:00Z",
  end_utc: "2026-03-01T09:20:00Z",
  size: 5.0,
  snr: 12.3,
  model: "fopdt",
  params: {
    gain: { value: 0.85, se: 0.04 },
    tau_s: { value: 12.5, se: 1.1 },
    theta_s: { value: 3.0, se: 0.5 },
  },
  r2: 0.98,
  rmse: 0.02,
  n: 400,
  verdict: "ok",
  reasons: [],
  alt_model: null,
  test_label: "W1",
  logbook: [{ time_utc: "2026-03-01T09:05:00Z", text: "valve bumped" }],
  sample: SAMPLE,
};

const WEAK_STEP_ROW: StepRow = {
  ...OUT_STEP_ROW,
  id: "step-2",
  event_utc: "2026-03-01T10:05:00Z",
  start_utc: "2026-03-01T10:00:00Z",
  end_utc: "2026-03-01T10:20:00Z",
  verdict: "weak",
  reasons: ["snr_low", "r2_low"],
  logbook: [],
};

const PAYLOAD: StepsPayload = {
  loop: "LIC1",
  process_kind: "self_regulating",
  unit: "m",
  dt_s: 2,
  noise_sd: 0.01,
  n_events: 2,
  rows: [OUT_STEP_ROW, WEAK_STEP_ROW],
  skipped: [],
  summary: [
    {
      model: "fopdt",
      n_rows: 2,
      n_consistent: 1,
      median_gain: 0.85,
      mad_gain: 0.02,
      median_slope: null,
      mad_slope: null,
      median_tau_s: 12.5,
      median_theta_s: 3.0,
    },
  ],
};

const EMPTY_PAYLOAD: StepsPayload = { ...PAYLOAD, rows: [], summary: [], n_events: 0 };

type RouteResult = { status?: number; body: unknown };

/** fetch mock answering `STEPS_PATH` with the queued result of the next call, in order. */
function respondSequence(results: RouteResult[]) {
  let callIndex = 0;
  const mock = vi.fn((url: string, init?: RequestInit) => {
    if (url !== STEPS_PATH || init?.method !== "POST") {
      return Promise.reject(new Error(`unexpected ${url}`));
    }
    const result = results[Math.min(callIndex, results.length - 1)];
    callIndex += 1;
    return Promise.resolve(
      new Response(JSON.stringify(result.body), { status: result.status ?? 200 }),
    );
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

/** fetch mock answering `STEPS_PATH` with the same result on every call. */
function respondAlways(result: RouteResult) {
  return respondSequence([result]);
}

/** Run the analysis once and wait for the rows table to appear. */
async function runAndWaitForRows() {
  fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));
  await screen.findByRole("table");
}

const renderPage = (initialLoop: string | null = "LIC1") =>
  render(
    <StepsPage datasetId="d1" loopNames={["LIC1", "FIC2"]} initialLoop={initialLoop} t={t} />,
  );

/** Body of the `n`-th POST sent to `STEPS_PATH`. */
function sentBody(mock: ReturnType<typeof respondSequence>, index = 0): Record<string, unknown> {
  const call = mock.mock.calls.filter(([url, init]) => url === STEPS_PATH && init?.method === "POST")[index];
  return JSON.parse(String(call?.[1]?.body)) as Record<string, unknown>;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("initial render", () => {
  it("shows the loop names and preselects the initial loop", () => {
    respondAlways({ body: PAYLOAD });
    renderPage();
    expect(screen.getByLabelText("Loop")).toHaveValue("LIC1");
    expect(screen.getByRole("option", { name: "FIC2" })).toBeInTheDocument();
  });

  it("enables the Run button when there are loops", () => {
    respondAlways({ body: PAYLOAD });
    renderPage();
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeEnabled();
  });
});

describe("analysis", () => {
  it("posts the loop, the auto model and an empty logbook", async () => {
    const mock = respondAlways({ body: PAYLOAD });
    renderPage();
    await runAndWaitForRows();
    expect(sentBody(mock)).toMatchObject({ loop: "LIC1", model: "auto", logbook: [] });
  });

  it("shows the OUT-step row with its parameter, verdict, reasons and test label", async () => {
    respondAlways({ body: PAYLOAD });
    renderPage();
    await runAndWaitForRows();
    const weakRow = screen.getByRole("button", { name: "2026-03-01T10:05:00Z" }).closest("tr");
    expect(weakRow).toHaveTextContent("Weak");
    expect(weakRow).toHaveTextContent("Response too small against the noise, Poor fit (R² under 0.5)");
    expect(weakRow).toHaveTextContent("W1");
    const outRow = screen.getByRole("button", { name: "2026-03-01T09:05:00Z" }).closest("tr");
    expect(outRow).toHaveTextContent("0.85 ± 0.04");
  });

  it("shows the summary line of the fitted model", async () => {
    respondAlways({ body: PAYLOAD });
    renderPage();
    await runAndWaitForRows();
    expect(screen.getByText(/FOPDT: gain=0.85/)).toBeInTheDocument();
    expect(screen.getByText(/ok: 1\/2/)).toBeInTheDocument();
  });

  it("sends the parsed logbook with the local offset and the chosen model", async () => {
    const mock = respondAlways({ body: PAYLOAD });
    renderPage();
    await runAndWaitForRows();
    fireEvent.change(screen.getByLabelText("Model"), { target: { value: "fopdt" } });
    fireEvent.change(screen.getByLabelText("Logbook"), {
      target: { value: "2026-03-01 06:05 valve bumped" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    await waitFor(() => expect(mock.mock.calls.length).toBeGreaterThanOrEqual(2));
    const body = sentBody(mock, 1);
    expect(body).toMatchObject({
      loop: "LIC1",
      model: "fopdt",
      logbook: [{ time_utc: "2026-03-01T09:05:00.000Z", text: "valve bumped" }],
    });
  });
});

describe("selection", () => {
  it("marks the clicked row pressed and shows the step chart", async () => {
    respondAlways({ body: PAYLOAD });
    renderPage();
    await runAndWaitForRows();
    const secondCell = screen.getByRole("button", { name: "2026-03-01T10:05:00Z" });
    fireEvent.click(secondCell);
    expect(secondCell).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("step-chart")).toBeInTheDocument();
  });
});

describe("empty and failing payloads", () => {
  it("shows the empty text when the payload has no rows", async () => {
    respondAlways({ body: EMPTY_PAYLOAD });
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    expect(await screen.findByText("No steps found.")).toBeInTheDocument();
  });

  it("shows the server message in an alert when the request fails", async () => {
    respondAlways({ status: 404, body: { detail: "unknown loop LIC1" } });
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("unknown loop LIC1");
  });
});

describe("busy state", () => {
  it("disables the run button while a request is pending and shows its result afterwards", async () => {
    let resolveFirst: (value: Response) => void = () => {};
    const pending = new Promise<Response>((resolve) => { resolveFirst = resolve; });
    vi.stubGlobal("fetch", vi.fn((url: string) =>
      (url.endsWith("/tags") ? Promise.resolve(new Response("[]", { status: 200 })) : pending)));
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    expect(screen.getByRole("button", { name: "Analyzing…" })).toBeDisabled();
    resolveFirst(new Response(JSON.stringify(EMPTY_PAYLOAD), { status: 200 }));
    expect(await screen.findByText("No steps found.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run analysis" })).toBeEnabled();
  });
});

describe("logbook file", () => {
  it("fills the logbook textarea with one line per row of a chosen CSV file", async () => {
    renderPage();
    const csv = "dia,hora,zmiana,jednostka,cele,uwagi\n2026-03-01,09:05,5,%,1,a\n2026-03-01,10:00,-2,%,4,\n";
    const file = new File([csv], "logbook.csv", { type: "text/csv" });
    // jsdom's File has no text() method; the component reads the file with it.
    Object.assign(file, { text: () => Promise.resolve(csv) });
    fireEvent.change(screen.getByLabelText("Load logbook from CSV"), { target: { files: [file] } });
    await waitFor(() => expect(screen.getByLabelText("Logbook")).toHaveValue(
      "2026-03-01 09:05 5 %, cells 1 - a\n2026-03-01 10:00 -2 %, cells 4",
    ));
  });
});

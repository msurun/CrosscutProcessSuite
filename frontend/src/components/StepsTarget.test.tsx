// Tests of the Steps target choice: the tag-pair mode shows the two tag selects and hides the
// loop select, Run waits for both tags, and the POST carries driver and output. fetch is mocked
// for the tag list (GET) and the analysis (POST); the translator is the real English one.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
vi.mock("./TrendPane", () => ({ TrendPane: () => <div data-testid="trend-pane" /> }));
import { translate } from "../i18n";
import { StepsPage } from "./StepsPage";

const t = (key: string, params?: Record<string, string | number>) => translate("en", key, params);

const TAGS_PATH = "/api/datasets/d1/tags";
const STEPS_PATH = "/api/datasets/d1/steps";
const TAGS = [{ id: "PUMP_SPD" }, { id: "FIT_101" }, { id: "LIC1" }];
const EMPTY_STEPS = { loop: "PUMP_SPD -> FIT_101", process_kind: "self_regulating", unit: "m3/h",
  dt_s: 2, noise_sd: null, n_events: 0, rows: [], skipped: [], summary: [] };

/** fetch mock: the tag list on GET, the empty analysis on POST, anything else rejects. */
function routeFetch() {
  const mock = vi.fn((url: string, init?: RequestInit) => {
    if (url === TAGS_PATH && init?.method === undefined) {
      return Promise.resolve(new Response(JSON.stringify(TAGS), { status: 200 }));
    }
    if (url === STEPS_PATH && init?.method === "POST") {
      return Promise.resolve(new Response(JSON.stringify(EMPTY_STEPS), { status: 200 }));
    }
    return Promise.reject(new Error(`unexpected ${url}`));
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

/** Body of the first POST sent to the steps path. */
function sentStepsBody(mock: ReturnType<typeof routeFetch>): Record<string, unknown> {
  const call = mock.mock.calls.find(([url, init]) => url === STEPS_PATH && init?.method === "POST");
  return JSON.parse(String(call?.[1]?.body)) as Record<string, unknown>;
}

/** Render the page with one loop and switch the target to the tag pair. */
async function renderTagMode() {
  render(<StepsPage datasetId="d1" loopNames={["LIC1"]} initialLoop="LIC1" t={t} />);
  fireEvent.click(screen.getByLabelText("Tag pair: stepped tag and response"));
  await waitFor(() => expect(optionLabels("Response tag")).toContain("PUMP_SPD"));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("stepsTarget_ target choice", () => {
  it("stepsTarget_ shows the two tag selects and hides the loop select in tag mode", async () => {
    routeFetch();
    await renderTagMode();
    expect(screen.getByLabelText("Stepped tag (e.g. pump speed)")).toBeInTheDocument();
    expect(screen.getByLabelText("Response tag")).toBeInTheDocument();
    expect(screen.queryByLabelText("Loop")).not.toBeInTheDocument();
  });

  it("stepsTarget_ keeps the loop select and no tag selects in loop mode", () => {
    routeFetch();
    render(<StepsPage datasetId="d1" loopNames={["LIC1"]} initialLoop="LIC1" t={t} />);
    expect(screen.getByLabelText("Loop")).toBeInTheDocument();
    expect(screen.queryByLabelText("Response tag")).not.toBeInTheDocument();
  });

  it("stepsTarget_ lists the dataset tags sorted with an empty first option", async () => {
    routeFetch();
    await renderTagMode();
    expect(optionLabels("Response tag")).toEqual(["—", "FIT_101", "LIC1", "PUMP_SPD"]);
  });

  it("stepsTarget_ keeps Run disabled until both tags are chosen", async () => {
    routeFetch();
    await renderTagMode();
    const run = screen.getByRole("button", { name: "Run analysis" });
    expect(run).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Stepped tag (e.g. pump speed)"), { target: { value: "PUMP_SPD" } });
    expect(run).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Response tag"), { target: { value: "FIT_101" } });
    expect(run).toBeEnabled();
  });

  it("stepsTarget_ posts driver and output without a loop in tag mode", async () => {
    const mock = routeFetch();
    await renderTagMode();
    fireEvent.change(screen.getByLabelText("Stepped tag (e.g. pump speed)"), { target: { value: "PUMP_SPD" } });
    fireEvent.change(screen.getByLabelText("Response tag"), { target: { value: "FIT_101" } });
    fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    await screen.findByText("No steps found.");
    const body = sentStepsBody(mock);
    expect(body).toMatchObject({ driver: "PUMP_SPD", output: "FIT_101", model: "auto", logbook: [] });
    expect(body).not.toHaveProperty("loop");
  });
});

/** Option labels of the select labelled `label`, in order. */
function optionLabels(label: string): string[] {
  return Array.from(screen.getByLabelText(label).querySelectorAll("option")).map((option) => option.textContent ?? "");
}

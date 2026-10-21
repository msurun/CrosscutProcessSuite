// Tests of the backtest tab: banner, settings sent to the API, result table and a 422 error.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, backtestFuzzy, type FuzzyBacktest } from "../api";
import type { FuzzyDocument } from "../fuzzy";
import { BacktestPanel } from "./BacktestPanel";

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  backtestFuzzy: vi.fn(),
}));

const t = (key: string, params?: Record<string, string | number>) => key + (params ? JSON.stringify(params) : "");

const document_: FuzzyDocument = {
  name: "demo",
  inputs: [],
  outputs: [
    { id: "feed", label: "Feed", low: 0, high: 100, tag: "feed_sp", terms: [] },
    { id: "water", low: 0, high: 10, terms: [] },
  ],
  rules: [],
} as unknown as FuzzyDocument;

const metrics = { n_moves: 12, sign_agreement: 0.75, correlation: null, majority_share: 0.6, silent_share: 0.1 };
const result: FuzzyBacktest = { output: "feed", all: metrics, first_half: metrics, second_half: { ...metrics, n_moves: 0 } };

beforeEach(() => {
  vi.mocked(backtestFuzzy).mockReset();
});

describe("BacktestPanel", () => {
  it("shows the advisory banner as a note before any run", () => {
    render(<BacktestPanel datasetId="ds" document={document_} t={t} />);
    expect(screen.getByRole("note")).toHaveTextContent("fuzzy.backtest.banner");
  });

  it("runs with the default settings and renders the table", async () => {
    vi.mocked(backtestFuzzy).mockResolvedValue(result);
    render(<BacktestPanel datasetId="ds" document={document_} t={t} />);
    fireEvent.click(screen.getByRole("button", { name: "fuzzy.backtest.run" }));
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(backtestFuzzy).toHaveBeenCalledWith("ds", document_, "feed", { deadBand: 2, lookbackS: 900, silentBand: 1 });
    expect(screen.getAllByText("75%").length).toBeGreaterThan(0);
    expect(screen.getAllByText("\u2014").length).toBeGreaterThan(0);
  });

  it("sends the chosen output", async () => {
    vi.mocked(backtestFuzzy).mockResolvedValue(result);
    render(<BacktestPanel datasetId="ds" document={document_} t={t} />);
    fireEvent.change(screen.getByLabelText("fuzzy.backtest.output"), { target: { value: "water" } });
    fireEvent.click(screen.getByRole("button", { name: "fuzzy.backtest.run" }));
    await waitFor(() => expect(backtestFuzzy).toHaveBeenCalled());
    expect(vi.mocked(backtestFuzzy).mock.calls[0][2]).toBe("water");
  });

  it("shows the server reason of a 422", async () => {
    vi.mocked(backtestFuzzy).mockImplementation(async () => {
      throw new ApiError(422, "output feed has no SP column");
    });
    render(<BacktestPanel datasetId="ds" document={document_} t={t} />);
    fireEvent.click(screen.getByRole("button", { name: "fuzzy.backtest.run" }));
    expect(await screen.findByText(/output feed has no SP column/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("disables the run button for an invalid setting", () => {
    render(<BacktestPanel datasetId="ds" document={document_} t={t} />);
    fireEvent.change(screen.getByLabelText("fuzzy.backtest.lookback"), { target: { value: "" } });
    expect(screen.getByRole("button", { name: "fuzzy.backtest.run" })).toBeDisabled();
  });
});

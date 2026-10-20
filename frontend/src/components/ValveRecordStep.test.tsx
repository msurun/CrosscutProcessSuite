// src/components/ValveRecordStep.test.tsx
// Behaviour tests for ValveRecordStep: switching between window and CSV, analyse callbacks, errors.
// WindowPicker is replaced by a stub that selects a fixed window.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { makeLoop } from "../testFixtures";
import { ValveRecordStep } from "./ValveRecordStep";

vi.mock("./WindowPicker", () => ({
  WindowPicker: ({ onSelectWindow }: { onSelectWindow: (w: { startS: number; endS: number }) => void }) => (
    <button type="button" onClick={() => onSelectWindow({ startS: 60, endS: 600 })}>
      pick-window
    </button>
  ),
}));

/** Fake translator: the key plus stringified params. */
const t = (key: string, params?: Record<string, string | number>) =>
  key + (params ? JSON.stringify(params) : "");

/** Renders the step; overrides tweak busy and error. */
function setup(overrides: { busy?: boolean; errorText?: string | null } = {}) {
  const onAnalyseWindow = vi.fn();
  const onAnalyseCsv = vi.fn();
  const onBack = vi.fn();
  render(
    <ValveRecordStep
      datasetId="ds1"
      loop={makeLoop()}
      busy={overrides.busy ?? false}
      errorText={overrides.errorText ?? null}
      onAnalyseWindow={onAnalyseWindow}
      onAnalyseCsv={onAnalyseCsv}
      onBack={onBack}
      t={t}
    />,
  );
  return { onAnalyseWindow, onAnalyseCsv, onBack };
}

/** The analyse button (its label is the same in both sources). */
const analyseButton = () => screen.getByRole("button", { name: /valve\.record\.analys/ });

describe("ValveRecordStep", () => {
  it("starts on the dataset source with analyse disabled and a hint", () => {
    setup();

    expect(screen.getByLabelText("valve.record.fromDataset")).toBeChecked();
    expect(screen.getByText("valve.record.windowNeeded")).toBeInTheDocument();
    expect(analyseButton()).toBeDisabled();
  });

  it("sends the picked window to onAnalyseWindow", () => {
    const { onAnalyseWindow } = setup();

    fireEvent.click(screen.getByRole("button", { name: "pick-window" }));
    expect(screen.queryByText("valve.record.windowNeeded")).not.toBeInTheDocument();
    fireEvent.click(analyseButton());

    expect(onAnalyseWindow).toHaveBeenCalledWith({ startS: 60, endS: 600 });
  });

  it("switches to the CSV source and hides the window picker", () => {
    setup();

    fireEvent.click(screen.getByLabelText("valve.record.fromCsv"));

    expect(screen.getByLabelText("valve.record.fromCsv")).toBeChecked();
    expect(screen.getByText("valve.record.csvHelp")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "pick-window" })).not.toBeInTheDocument();
    expect(analyseButton()).toBeDisabled();
  });

  it("reads a CSV file and sends its text to onAnalyseCsv", async () => {
    const { onAnalyseCsv } = setup();
    fireEvent.click(screen.getByLabelText("valve.record.fromCsv"));

    // jsdom's File has no text(); give the real File one.
    const csv = "t_s,OP,PV\n0,50,10\n";
    const file = new File([csv], "test.csv", { type: "text/csv" });
    Object.defineProperty(file, "text", { value: () => Promise.resolve(csv) });
    fireEvent.change(screen.getByLabelText(/valve\.record\.csvChoose/), { target: { files: [file] } });

    await waitFor(() => expect(analyseButton()).toBeEnabled());
    expect(screen.getByText('valve.record.csvName{"name":"test.csv"}')).toBeInTheDocument();
    fireEvent.click(analyseButton());
    expect(onAnalyseCsv).toHaveBeenCalledWith("t_s,OP,PV\n0,50,10\n");
  });

  it("disables analyse and shows the busy label while busy", () => {
    setup({ busy: true });

    expect(screen.getByRole("button", { name: "valve.record.analysing" })).toBeDisabled();
  });

  it("shows the error text as an alert when given", () => {
    setup({ errorText: "bad csv" });

    expect(screen.getByRole("alert")).toHaveTextContent("valve.error.title: bad csv");
  });

  it("shows no alert without an error", () => {
    setup();

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("calls onBack", () => {
    const { onBack } = setup();

    fireEvent.click(screen.getByRole("button", { name: "valve.record.back" }));

    expect(onBack).toHaveBeenCalledTimes(1);
  });
});

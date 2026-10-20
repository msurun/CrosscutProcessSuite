// src/components/ContextBar.test.tsx

/**
 * Behaviour tests for ContextBar: which items are shown for a given dataset and analysis.
 * The translator is a fake that returns the key plus its params as JSON, so assertions
 * can look at keys and parameters without pulling in the real i18n bundle.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import type { DatasetSummary } from "../api";
import type { Translate } from "../findings";
import { ContextBar } from "./ContextBar";

/** Fake translator: key plus its params (if any) as JSON, so tests can assert on both. */
const t: Translate = (key, params) => (params ? key + JSON.stringify(params) : key);

/** Build a dataset from start/end ISO strings and a sample count; span in tags is fixed. */
function makeDataset(params: {
  startIso: string;
  endIso: string;
  nSamples: number;
  source?: Record<string, unknown>;
}): DatasetSummary {
  return {
    id: "line1-reactor",
    source: params.source ?? { kind: "sim" },
    time_range: { start_utc: params.startIso, end_utc: params.endIso },
    n_tags: 3,
    n_samples: params.nSamples,
  };
}

beforeEach(() => {
  document.documentElement.lang = "en";
});

describe("ContextBar", () => {
  it("renders nothing without a dataset", () => {
    render(<ContextBar dataset={undefined} analysis={null} t={t} />);

    expect(screen.queryByRole("region")).not.toBeInTheDocument();
  });

  it("shows the dataset id", () => {
    const dataset = makeDataset({
      startIso: "2024-01-01T00:00:00Z",
      endIso: "2024-01-02T00:00:00Z",
      nSamples: 8640,
    });

    render(<ContextBar dataset={dataset} analysis={null} t={t} />);

    expect(screen.getByText("line1-reactor")).toBeInTheDocument();
  });

  it("shows the tag count as a plain integer", () => {
    const dataset = makeDataset({
      startIso: "2024-01-01T00:00:00Z",
      endIso: "2024-01-02T00:00:00Z",
      nSamples: 8640,
    });

    render(<ContextBar dataset={dataset} analysis={null} t={t} />);

    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("shows a sample period of 10 s for a 24 h span with 8640 samples", () => {
    // Span = 86390 s over 8639 intervals = 10 s per sample.
    const dataset = makeDataset({
      startIso: "2024-01-01T00:00:00Z",
      endIso: "2024-01-01T23:59:50Z",
      nSamples: 8640,
    });

    render(<ContextBar dataset={dataset} analysis={null} t={t} />);

    expect(screen.getByText("10.0 s")).toBeInTheDocument();
  });

  it("shows a sample period of 1.5 min for a 90 s period", () => {
    const dataset = makeDataset({
      startIso: "2024-01-01T00:00:00Z",
      endIso: "2024-01-01T00:01:30Z",
      nSamples: 2,
    });

    render(<ContextBar dataset={dataset} analysis={null} t={t} />);

    expect(screen.getByText("1.5 min")).toBeInTheDocument();
  });

  it("shows a dash when there is only one sample", () => {
    const dataset = makeDataset({
      startIso: "2024-01-01T00:00:00Z",
      endIso: "2024-01-01T00:00:00Z",
      nSamples: 1,
    });

    render(<ContextBar dataset={dataset} analysis={null} t={t} />);

    expect(screen.getByText("–")).toBeInTheDocument();
  });

  it("does not show the analysis line when no analysis is given", () => {
    const dataset = makeDataset({
      startIso: "2024-01-01T00:00:00Z",
      endIso: "2024-01-02T00:00:00Z",
      nSamples: 8640,
    });

    render(<ContextBar dataset={dataset} analysis={null} t={t} />);

    expect(screen.queryByText(/context\.analysedAt/)).not.toBeInTheDocument();
  });

  it("shows the analysis time and duration when an analysis is given", () => {
    const dataset = makeDataset({
      startIso: "2024-01-01T00:00:00Z",
      endIso: "2024-01-02T00:00:00Z",
      nSamples: 8640,
    });
    const analysis = { finishedAt: new Date("2024-01-02T12:00:00Z"), tookMs: 25000 };

    render(<ContextBar dataset={dataset} analysis={analysis} t={t} />);

    expect(screen.getByText(/context\.analysedAt/)).toBeInTheDocument();
    // The timestamp and the duration share one <dd>, so match the duration as a substring.
    expect(screen.getByText(/context\.took\{"seconds":"25\.0"\}/)).toBeInTheDocument();
  });

  it("shows the source kind as a badge", () => {
    const dataset = makeDataset({
      startIso: "2024-01-01T00:00:00Z",
      endIso: "2024-01-02T00:00:00Z",
      nSamples: 8640,
      source: { kind: "sim" },
    });

    render(<ContextBar dataset={dataset} analysis={null} t={t} />);

    expect(screen.getByText("sim")).toHaveClass("badge");
  });
});

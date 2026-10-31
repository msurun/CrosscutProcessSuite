// src/components/CatalogueWizard.test.tsx
// Unit and behavioural tests for CatalogueWizard component (Phase 1, #37).

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { CatalogueWizard } from "./CatalogueWizard";

const mockT = (key: string) => key;

describe("CatalogueWizard", () => {
  beforeEach(() => {
    vi.spyOn(api, "fetchDatasets").mockResolvedValue([
      {
        id: "ds1",
        source: {},
        time_range: { start_utc: "2026-01-01T00:00:00Z", end_utc: "2026-01-01T01:00:00Z" },
        n_samples: 360,
        n_tags: 5,
      },
    ]);
    vi.spyOn(api, "fetchTags").mockResolvedValue([
      { id: "TIC101.PV", unit: "%" },
      { id: "TIC101.SP", unit: "%" },
      { id: "TIC101.OUT", unit: "%" },
      { id: "TIC101.MODE" },
      { id: "FEED_INLET", unit: "t/h" },
    ]);
    vi.spyOn(api, "suggestCatalogueRoles").mockResolvedValue({
      signals: [
        { tag: "TIC101.PV", role: "pv", loop: "TIC101" },
        { tag: "TIC101.SP", role: "sp", loop: "TIC101" },
        { tag: "TIC101.OUT", role: "out", loop: "TIC101" },
        { tag: "TIC101.MODE", role: "mode", loop: "TIC101" },
        { tag: "FEED_INLET", role: "input" },
      ],
      loops: [
        { id: "TIC101", pv: "TIC101.PV", sp: "TIC101.SP", out: "TIC101.OUT", mode: "TIC101.MODE" },
      ],
    });
    vi.spyOn(api, "saveCatalogueMapping").mockResolvedValue({
      status: "ok",
      signals: [],
      loops: [],
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the stepper and initial source step", async () => {
    render(<CatalogueWizard t={mockT} />);
    expect(screen.getByTestId("catalogue-wizard")).toBeDefined();
    expect(screen.getByTestId("wizard-step-source")).toBeDefined();
    await waitFor(() => {
      expect(screen.getByTestId("wizard-dataset-select")).toBeDefined();
    });
  });

  it("navigates through source -> tags -> roles -> loops -> confirm and saves mapping", async () => {
    const onSaved = vi.fn();
    render(<CatalogueWizard t={mockT} onSaved={onSaved} />);

    // Step 1: Source (select dataset)
    await waitFor(() => {
      expect(screen.getByTestId("wizard-dataset-select")).toBeDefined();
    });
    fireEvent.click(screen.getByText("catalogue.wizard.nextTags"));

    // Step 2: Tags
    await waitFor(() => {
      expect(screen.getByTestId("wizard-step-tags")).toBeDefined();
    });
    expect(screen.getByText("5 tags discovered.")).toBeDefined();
    fireEvent.click(screen.getByText("catalogue.wizard.nextRoles"));

    // Step 3: Roles
    await waitFor(() => {
      expect(screen.getByTestId("wizard-step-roles")).toBeDefined();
    });
    expect(api.suggestCatalogueRoles).toHaveBeenCalledWith([
      "TIC101.PV", "TIC101.SP", "TIC101.OUT", "TIC101.MODE", "FEED_INLET",
    ]);
    fireEvent.click(screen.getByText("catalogue.wizard.nextLoops"));

    // Step 4: Loops
    await waitFor(() => {
      expect(screen.getByTestId("wizard-step-loops")).toBeDefined();
    });
    expect(screen.getByText("TIC101")).toBeDefined();
    fireEvent.click(screen.getByText("catalogue.wizard.nextConfirm"));

    // Step 5: Confirm and save
    await waitFor(() => {
      expect(screen.getByTestId("wizard-step-confirm")).toBeDefined();
    });
    fireEvent.click(screen.getByTestId("wizard-save-btn"));

    await waitFor(() => {
      expect(api.saveCatalogueMapping).toHaveBeenCalled();
      expect(screen.getByTestId("wizard-success-notice")).toBeDefined();
      expect(onSaved).toHaveBeenCalled();
    });
  });

  it("supports pasting raw tags manually", async () => {
    render(<CatalogueWizard t={mockT} />);
    const manualRadio = screen.getByLabelText("catalogue.wizard.sourceManual");
    fireEvent.click(manualRadio);

    const textarea = screen.getByTestId("wizard-manual-textarea");
    fireEvent.change(textarea, { target: { value: "A.PV, A.OUT, B_TARGET" } });
    fireEvent.click(screen.getByText("catalogue.wizard.nextTags"));

    await waitFor(() => {
      expect(screen.getByTestId("wizard-step-tags")).toBeDefined();
      expect(screen.getByText("3 tags discovered.")).toBeDefined();
    });
  });
});

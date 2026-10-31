// src/components/OnboardingPage.test.tsx
/**
 * Unit tests for OnboardingPage component (Phase 1, #39).
 * Verifies rendering of traffic lights, overall verdict, and what-to-fix guidance.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { OnboardingPage } from "./OnboardingPage";

const mockT = (key: string, params?: Record<string, string | number>) => {
  if (params && params.count !== undefined) {
    return `${key}:${params.count}`;
  }
  return key;
};

describe("OnboardingPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders loading state and overall readiness traffic light", async () => {
    vi.spyOn(api, "fetchDatasetReadiness").mockResolvedValue({
      dataset_id: "ds_clean",
      verdict: "ok",
      modules: {
        loops: { status: "ok", reasons: [], items_checked: 3 },
        anomaly: { status: "ok", reasons: [], items_checked: 5 },
        softsensor: { status: "ok", reasons: [], items_checked: 4 },
      },
    });

    render(<OnboardingPage datasetId="ds_clean" t={mockT} />);
    expect(screen.getByText("onboarding.loading")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId("onboarding-page")).toBeInTheDocument();
    });

    expect(screen.getByTestId("onboarding-overall-verdict")).toHaveTextContent("onboarding.status.ok");
    expect(screen.getByTestId("onboarding-module-loops")).toBeInTheDocument();
    expect(screen.getByTestId("onboarding-module-anomaly")).toBeInTheDocument();
    expect(screen.getByTestId("onboarding-module-softsensor")).toBeInTheDocument();
    expect(screen.getAllByText("onboarding.allChecksPassed")).toHaveLength(3);
  });

  it("displays what-to-fix reasons for warning and not_ready statuses", async () => {
    vi.spyOn(api, "fetchDatasetReadiness").mockResolvedValue({
      dataset_id: "ds_faulty",
      verdict: "not_ready",
      modules: {
        loops: {
          status: "warning",
          reasons: ["Loop 'FIC101' has no OUT tag mapped (monitoring only)."],
          items_checked: 1,
        },
        anomaly: { status: "ok", reasons: [], items_checked: 2 },
        softsensor: {
          status: "not_ready",
          reasons: ["No target tag mapped for soft sensor."],
          items_checked: 0,
        },
      },
    });

    render(<OnboardingPage datasetId="ds_faulty" t={mockT} />);

    await waitFor(() => {
      expect(screen.getByTestId("onboarding-overall-verdict")).toHaveTextContent("onboarding.status.not_ready");
    });

    expect(screen.getByText("Loop 'FIC101' has no OUT tag mapped (monitoring only).")).toBeInTheDocument();
    expect(screen.getByText("No target tag mapped for soft sensor.")).toBeInTheDocument();
    expect(screen.getAllByText("onboarding.whatToFix")).toHaveLength(2);
  });

  it("handles fetch failure with retry button", async () => {
    const fetchMock = vi.spyOn(api, "fetchDatasetReadiness")
      .mockRejectedValueOnce(new Error("Network offline"))
      .mockResolvedValueOnce({
        dataset_id: "ds_retry",
        verdict: "ok",
        modules: {
          loops: { status: "ok", reasons: [], items_checked: 1 },
        },
      });

    render(<OnboardingPage datasetId="ds_retry" t={mockT} />);

    await waitFor(() => {
      expect(screen.getByText("Network offline")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("onboarding.retry"));

    await waitFor(() => {
      expect(screen.getByTestId("onboarding-page")).toBeInTheDocument();
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

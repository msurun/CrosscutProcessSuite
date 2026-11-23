// frontend/src/components/SavedChartsPanel.test.tsx
/**
 * Unit tests for SavedChartsPanel component.
 * Verifies rendering of "My charts" and "Shared charts" sections, loading and error states,
 * and interaction with the trendChartsApi.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { ApiError } from "../api";
import { SavedChartsPanel } from "./SavedChartsPanel";
import type { ChartSummary, TrendChart } from "../trendChartsApi";

vi.mock("../trendChartsApi", () => ({
  listCharts: vi.fn(),
  getChart: vi.fn(),
  saveChart: vi.fn(),
  copyChart: vi.fn(),
  deleteChart: vi.fn(),
}));

import { copyChart, listCharts } from "../trendChartsApi";

const mockedCopy = vi.mocked(copyChart);

const mockedList = vi.mocked(listCharts);

const mockT = (key: string, vars?: Record<string, string | number>) =>
  vars ? `${key} ${JSON.stringify(vars)}` : key;

const mockCharts: ChartSummary[] = [
  {
    id: "1",
    name: "Chart 1",
    owner: "user1",
    shared: false,
    updated_utc: "2023-01-01T00:00:00Z",
    mine: true,
  },
  {
    id: "2",
    name: "Chart 2",
    owner: "user2",
    shared: true,
    updated_utc: "2023-01-02T00:00:00Z",
    mine: false,
  },
];

describe("SavedChartsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders 'My charts' and 'Shared charts' sections with the right rows", async () => {
    mockedList.mockResolvedValue({ charts: mockCharts });

    render(
      <SavedChartsPanel
        t={mockT}
        canShare={true}
        activeId={null}
        onOpen={vi.fn()}
        reloadToken={0}
      />
    );

    await waitFor(() => {
      expect(screen.getByText("savedCharts.title")).toBeInTheDocument();
      expect(screen.getByText("savedCharts.myCharts")).toBeInTheDocument();
      expect(screen.getByText("savedCharts.sharedCharts")).toBeInTheDocument();
      expect(screen.getByText("Chart 1")).toBeInTheDocument();
      expect(screen.getByText("Chart 2")).toBeInTheDocument();
    });
  });

  it("shows loading then empty state when listCharts returns []", async () => {
    mockedList.mockResolvedValue({ charts: [] });

    render(
      <SavedChartsPanel
        t={mockT}
        canShare={true}
        activeId={null}
        onOpen={vi.fn()}
        reloadToken={0}
      />
    );

    expect(screen.getByText("savedCharts.loading")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("savedCharts.empty")).toBeInTheDocument();
    });
  });

  it("shows error message from ApiError when listCharts rejects", async () => {
    const errorMessage = "Failed to fetch charts";
    mockedList.mockRejectedValue(new ApiError(500, errorMessage));

    render(
      <SavedChartsPanel
        t={mockT}
        canShare={true}
        activeId={null}
        onOpen={vi.fn()}
        reloadToken={0}
      />
    );

    await waitFor(() => {
      expect(screen.getByText(`savedCharts.error: ${errorMessage}`)).toBeInTheDocument();
    });
  });

  it("calls onOpen with id when name button clicked", async () => {
    mockedList.mockResolvedValue({ charts: mockCharts });
    const onOpen = vi.fn();

    render(
      <SavedChartsPanel
        t={mockT}
        canShare={true}
        activeId={null}
        onOpen={onOpen}
        reloadToken={0}
      />
    );

    await waitFor(() => {
      const chart1Button = screen.getByLabelText("savedCharts.open Chart 1");
      fireEvent.click(chart1Button);
      expect(onOpen).toHaveBeenCalledWith("1");
    });
  });

  it("aria-current='true' only on activeId row", async () => {
    mockedList.mockResolvedValue({ charts: mockCharts });

    const { rerender } = render(
      <SavedChartsPanel
        t={mockT}
        canShare={true}
        activeId="1"
        onOpen={vi.fn()}
        reloadToken={0}
      />
    );

    await waitFor(() => {
      const chart1Row = screen.getByText("Chart 1").closest("li");
      expect(chart1Row).toHaveAttribute("aria-current", "true");

      const chart2Row = screen.getByText("Chart 2").closest("li");
      expect(chart2Row).not.toHaveAttribute("aria-current");
    });

    rerender(
      <SavedChartsPanel
        t={mockT}
        canShare={true}
        activeId="2"
        onOpen={vi.fn()}
        reloadToken={0}
      />
    );

    await waitFor(() => {
      const chart1Row = screen.getByText("Chart 1").closest("li");
      expect(chart1Row).not.toHaveAttribute("aria-current");

      const chart2Row = screen.getByText("Chart 2").closest("li");
      expect(chart2Row).toHaveAttribute("aria-current", "true");
    });
  });

  it("Share toggle button only rendered when canShare=true", async () => {
    mockedList.mockResolvedValue({ charts: mockCharts });

    const { rerender } = render(
      <SavedChartsPanel
        t={mockT}
        canShare={true}
        activeId={null}
        onOpen={vi.fn()}
        reloadToken={0}
      />
    );

    await waitFor(() => {
      expect(screen.getByText("savedCharts.share")).toBeInTheDocument();
    });

    rerender(
      <SavedChartsPanel
        t={mockT}
        canShare={false}
        activeId={null}
        onOpen={vi.fn()}
        reloadToken={0}
      />
    );

    await waitFor(() => {
      expect(screen.queryByText("savedCharts.share")).not.toBeInTheDocument();
    });
  });

  it("Copy button shown for shared charts of others and calls copyChart", async () => {
    mockedList.mockResolvedValue({ charts: mockCharts });
    mockedCopy.mockResolvedValue({} as TrendChart);

    render(
      <SavedChartsPanel
        t={mockT}
        canShare={true}
        activeId={null}
        onOpen={vi.fn()}
        reloadToken={0}
      />
    );

    await waitFor(() => {
      const copyButton = screen.getByLabelText(
        `savedCharts.ariaCopy ${JSON.stringify({ name: "Chart 2" })}`
      );
      fireEvent.click(copyButton);
      expect(copyChart).toHaveBeenCalledWith("2");
    });
  });

  it("reloads listCharts when reloadToken prop changes", async () => {
    mockedList.mockResolvedValue({ charts: mockCharts });

    const { rerender } = render(
      <SavedChartsPanel
        t={mockT}
        canShare={true}
        activeId={null}
        onOpen={vi.fn()}
        reloadToken={0}
      />
    );

    await waitFor(() => {
      expect(listCharts).toHaveBeenCalledTimes(1);
    });

    rerender(
      <SavedChartsPanel
        t={mockT}
        canShare={true}
        activeId={null}
        onOpen={vi.fn()}
        reloadToken={1}
      />
    );

    await waitFor(() => {
      expect(listCharts).toHaveBeenCalledTimes(2);
    });
  });
});

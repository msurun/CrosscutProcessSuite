// src/components/SourcesPanel.test.tsx
// Unit tests for the SourcesPanel component (Phase 1, #43).

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { SourcesPanel } from "./SourcesPanel";

const mockT = (key: string) => key;

describe("SourcesPanel", () => {
  beforeEach(() => {
    vi.spyOn(api, "fetchSources").mockResolvedValue({
      sources: [
        { id: "opcua_src", driver: "opcua", endpoint: "opc.tcp://127.0.0.1:4840" },
        { id: "csv_src", driver: "csv", endpoint: "/data/csv" },
      ],
    });
    vi.spyOn(api, "testSource").mockResolvedValue({
      status: "ok",
      source_id: "opcua_src",
      capabilities: ["browse", "read_live"],
    });
    vi.spyOn(api, "browseSource").mockResolvedValue({
      source_id: "opcua_src",
      nodes: [
        { id: "ns=2;s=Plant", name: "Plant", node_type: "object", has_children: true },
        { id: "ns=2;s=FIC101.PV", name: "FIC101.PV", node_type: "variable", has_children: false },
      ],
    });
    vi.spyOn(api, "readSourceLive").mockResolvedValue({
      source_id: "opcua_src",
      values: {
        "ns=2;s=FIC101.PV": { value: 42.5, quality: 0, timestamp_utc: "2026-01-01T00:00:00Z" },
      },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders configured sources list", async () => {
    render(<SourcesPanel t={mockT} />);

    await waitFor(() => {
      expect(screen.getByTestId("sources-panel")).toBeInTheDocument();
    });

    expect(screen.getByText("opcua_src")).toBeInTheDocument();
    expect(screen.getByText("csv_src")).toBeInTheDocument();
  });

  it("tests connection and displays capabilities", async () => {
    render(<SourcesPanel t={mockT} />);

    await waitFor(() => {
      expect(screen.getByTestId("test-source-opcua_src")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("test-source-opcua_src"));

    await waitFor(() => {
      expect(screen.getByText("browse")).toBeInTheDocument();
      expect(screen.getByText("read_live")).toBeInTheDocument();
    });
  });

  it("browses nodes and samples live variable value", async () => {
    render(<SourcesPanel t={mockT} />);

    await waitFor(() => {
      expect(screen.getByTestId("browse-source-opcua_src")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("browse-source-opcua_src"));

    await waitFor(() => {
      expect(screen.getByTestId("browse-results")).toBeInTheDocument();
      expect(screen.getByText("Plant")).toBeInTheDocument();
      expect(screen.getByText("FIC101.PV")).toBeInTheDocument();
    });

    const readLiveBtn = screen.getByTestId("read-live-ns=2;s=FIC101.PV");
    fireEvent.click(readLiveBtn);

    await waitFor(() => {
      expect(screen.getByText("42.5")).toBeInTheDocument();
    });
  });
});

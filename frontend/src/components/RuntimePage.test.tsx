// src/components/RuntimePage.test.tsx
/**
 * Unit tests for the Runtime page (Phase 1, #44).
 * Verifies the service status and the jobs table, the start/stop actions and
 * that the 422 problems of a refused new job are listed line by line.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { RuntimePage } from "../RuntimePage";

/** Returns the key itself (with the count placeholder), like the other page tests do. */
const mockT = (key: string, params?: Record<string, string | number>) => {
  if (params && params.count !== undefined) {
    return `${key}:${params.count}`;
  }
  return key;
};

const statusFixture: api.RuntimeStatus = {
  service: { running: true, updated_at_utc: "2026-11-01T12:00:00Z" },
  jobs: [
    {
      id: "j1",
      kind: "loop_kpi",
      source: "src1",
      enabled: false,
      status: "idle",
      last_run_utc: null,
      error: null,
      samples: 0,
      kpi: { L1: { classification: "oscillating", harris_index: 2.4 } },
    },
    {
      id: "j2",
      kind: "anomaly_scan",
      source: "src1",
      enabled: true,
      status: "running",
      last_run_utc: "2026-11-01T11:59:00Z",
      error: null,
      samples: 17,
      kpi: null,
    },
  ],
};

const jobsDocumentFixture: api.RuntimeJobsDocument = {
  schema_version: 1,
  jobs: [
    { id: "j1", kind: "loop_kpi", source: "src1", loops: ["L1", "L2"], period_s: 60, window_s: 3600, enabled: false },
    { id: "j2", kind: "anomaly_scan", source: "src1", tags: ["T1"], period_s: 30, window_s: 600, enabled: true },
  ],
};

function mockRuntime() {
  vi.spyOn(api, "fetchRuntimeStatus").mockResolvedValue(statusFixture);
  vi.spyOn(api, "fetchRuntimeJobs").mockResolvedValue(jobsDocumentFixture);
  vi.spyOn(api, "fetchRuntimeLog").mockResolvedValue({ lines: ["line one", "line two"] });
}

describe("RuntimePage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the service status, the jobs table and the log", async () => {
    mockRuntime();

    render(<RuntimePage t={mockT} />);

    await waitFor(() => {
      expect(screen.getByTestId("runtime-service-status")).toHaveTextContent("runtime.service.running");
    });

    expect(screen.getByTestId("runtime-job-j1")).toBeInTheDocument();
    expect(screen.getByTestId("runtime-job-j2")).toBeInTheDocument();
    expect(screen.getByText("L1, L2")).toBeInTheDocument();
    expect(screen.getByText("T1")).toBeInTheDocument();
    expect(screen.getByText("L1: oscillating · runtime.kpi.harris 2.4")).toBeInTheDocument();
    expect(screen.getByTestId("runtime-log")).toHaveTextContent("line one");
    expect(screen.getByTestId("runtime-log")).toHaveTextContent("line two");
  });

  it("starts a stopped job through the start endpoint and refreshes the status", async () => {
    const statusMock = vi.spyOn(api, "fetchRuntimeStatus").mockResolvedValue(statusFixture);
    vi.spyOn(api, "fetchRuntimeJobs").mockResolvedValue(jobsDocumentFixture);
    vi.spyOn(api, "fetchRuntimeLog").mockResolvedValue({ lines: [] });
    const startMock = vi.spyOn(api, "startRuntimeJob").mockResolvedValue(jobsDocumentFixture);

    render(<RuntimePage t={mockT} />);
    await waitFor(() => {
      expect(screen.getByTestId("runtime-start-j1")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("runtime-start-j1"));

    expect(startMock).toHaveBeenCalledWith("j1");
    await waitFor(() => {
      expect(statusMock.mock.calls.length).toBeGreaterThan(1);
    });
  });

  it("stops an enabled job through the stop endpoint", async () => {
    mockRuntime();
    const stopMock = vi.spyOn(api, "stopRuntimeJob").mockResolvedValue(jobsDocumentFixture);

    render(<RuntimePage t={mockT} />);
    await waitFor(() => {
      expect(screen.getByTestId("runtime-stop-j2")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("runtime-stop-j2"));

    expect(stopMock).toHaveBeenCalledWith("j2");
  });

  it("sends the filled form as a job and lists the 422 problems", async () => {
    mockRuntime();
    const createMock = vi.spyOn(api, "createRuntimeJob").mockRejectedValue(
      new api.ApiError(422, "job.source: unknown source 'nope'\njob.loops: unknown loop 'ghost'"),
    );

    render(<RuntimePage t={mockT} />);

    fireEvent.change(screen.getByTestId("runtime-form-id"), { target: { value: "j3" } });
    fireEvent.change(screen.getByTestId("runtime-form-source"), { target: { value: "nope" } });
    fireEvent.change(screen.getByTestId("runtime-form-targets"), { target: { value: "ghost, " } });
    fireEvent.click(screen.getByTestId("runtime-create"));

    await waitFor(() => {
      expect(screen.getByTestId("runtime-problems")).toBeInTheDocument();
    });

    expect(createMock).toHaveBeenCalledWith({
      id: "j3",
      kind: "loop_kpi",
      source: "nope",
      period_s: 60,
      window_s: 3600,
      enabled: true,
      loops: ["ghost"],
    });
    expect(screen.getByText("job.source: unknown source 'nope'")).toBeInTheDocument();
    expect(screen.getByText("job.loops: unknown loop 'ghost'")).toBeInTheDocument();
  });
});

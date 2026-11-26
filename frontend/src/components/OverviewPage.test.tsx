// Verify independent monitoring tiles in loading, empty, unavailable and populated states.
// Mock only existing API clients so tests exercise the actual overview rendering.
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import * as controllersApi from "../controllersApi";
import * as equipmentApi from "../equipmentAnomalyApi";
import * as gatewayApi from "../gatewayApi";
import * as loopsApi from "../liveLoopsApi";
import { OverviewPage } from "../OverviewPage";

const t = (key: string) => key;

/** Successful empty endpoints establish the baseline for each state transition. */
function mockEmptySources() {
  vi.spyOn(api, "fetchRuntimeStatus").mockResolvedValue({ service: { running: true, updated_at_utc: null }, jobs: [] });
  vi.spyOn(controllersApi, "fetchControllers").mockResolvedValue([]);
  vi.spyOn(equipmentApi, "fetchEquipmentAnomalies").mockResolvedValue([]);
  vi.spyOn(gatewayApi, "fetchGatewayStatus").mockResolvedValue({ mode: "advisory", targets: {}, pending: 0 });
  vi.spyOn(loopsApi, "fetchLiveLoops").mockResolvedValue([]);
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("OverviewPage", () => {
  it("shows loading while the first worklist request is pending", () => {
    mockEmptySources();
    vi.mocked(loopsApi.fetchLiveLoops).mockReturnValue(new Promise(() => {}));
    render(<OverviewPage t={t} />);
    expect(within(screen.getByTestId("overview-worklist")).getByText("overview.loading")).toBeInTheDocument();
  });
  it("distinguishes a successful empty worklist from an unavailable one", async () => {
    mockEmptySources();
    render(<OverviewPage t={t} />);
    expect(await within(screen.getByTestId("overview-worklist")).findByText("overview.empty")).toBeInTheDocument();
    expect(screen.queryByText("overview.unavailable")).not.toBeInTheDocument();
  });
  it("keeps other tiles available when an endpoint rejects", async () => {
    mockEmptySources();
    vi.mocked(loopsApi.fetchLiveLoops).mockRejectedValue(new Error("Forbidden"));
    render(<OverviewPage t={t} />);
    expect(await within(screen.getByTestId("overview-worklist")).findByText("overview.unavailable")).toBeInTheDocument();
    expect(within(screen.getByTestId("overview-site")).getByText("runtime.service.running")).toBeInTheDocument();
  });
  it("renders worklist findings with a shortcut to the live loops view", async () => {
    mockEmptySources();
    vi.mocked(loopsApi.fetchLiveLoops).mockResolvedValue([{ id: "flow", name: "Flow loop", type: null,
      job: "kpi", job_status: "ok", last_run_utc: null, fresh: false, kpi: {},
      findings: [{ code: "stiction", since_utc: null }] }]);
    render(<OverviewPage t={t} />);
    expect(await screen.findByRole("link", { name: "Flow loop" })).toHaveAttribute("href", "#/d//loops");
    expect(screen.getByText(/finding.stiction/)).toHaveTextContent("overview.stale");
  });
  it("retains shelved anomaly evidence without showing an active alarm", async () => {
    mockEmptySources();
    vi.mocked(equipmentApi.fetchEquipmentAnomalies).mockResolvedValue([{ equipment_id: "pump", model_status: "learned",
      live_state: { status: "anomaly", shelved: true }, open_event: null, events: [], shelved_until_utc: null }]);
    render(<OverviewPage t={t} />);
    expect(await within(screen.getByTestId("overview-anomalies")).findByRole("link", { name: "pump" })).toBeInTheDocument();
    await waitFor(() => expect(within(screen.getByTestId("overview-alarms")).getByText("overview.empty")).toBeInTheDocument());
  });
  it("renders each controller state and its full-view shortcut", async () => {
    mockEmptySources();
    vi.mocked(controllersApi.fetchControllers).mockResolvedValue([{ id: "rougher", state: "on", record_unreadable: false } as controllersApi.ControllerSummary]);
    render(<OverviewPage t={t} />);
    expect(await screen.findByRole("link", { name: "rougher" })).toHaveAttribute("href", "#/controllers");
    expect(screen.getByText("controllers.state.on")).toBeInTheDocument();
  });
});

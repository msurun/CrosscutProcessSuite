// Component tests exercise equipment learning and operator feedback through the view.
// Synthetic API responses keep every mutation and visible state deterministic.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DatasetSummary } from "../api";
import { translate } from "../i18n";
import { EquipmentLearnForm } from "./EquipmentLearnForm";

const t = (key: string, params?: Record<string, string | number>) => translate("en", key, params);
const DATASET: DatasetSummary = {
  id: "pump-data", source: {}, n_tags: 2, n_samples: 300,
  time_range: { start_utc: "2026-01-01T00:00:00Z", end_utc: "2026-01-01T01:00:00Z" },
};

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("equipment learning form", () => {
  it("proposes the selected dataset's complete UTC range", () => {
    render(<EquipmentLearnForm datasets={[DATASET]} datasetId="pump-data" busy={false} t={t} onLearn={vi.fn()} />);
    expect(screen.getByTestId("learn-dataset")).toHaveValue("pump-data");
    expect(screen.getByTestId("learn-start")).toHaveValue(DATASET.time_range.start_utc);
    expect(screen.getByTestId("learn-end")).toHaveValue(DATASET.time_range.end_utc);
  });
  it("converts a narrowed window before invoking learning", async () => {
    const learn = vi.fn().mockResolvedValue(undefined);
    render(<EquipmentLearnForm datasets={[DATASET]} datasetId="pump-data" busy={false} t={t} onLearn={learn} />);
    fireEvent.change(screen.getByTestId("learn-start"), { target: { value: "2026-01-01T00:10:00Z" } });
    fireEvent.click(screen.getByTestId("learn-submit"));
    await waitFor(() => expect(learn).toHaveBeenCalledWith("pump-data", [
      [DATASET.time_range.start_utc, "2026-01-01T00:09:59.999Z"],
    ]));
  });
  it("refuses an invalid window before sending any request", async () => {
    const learn = vi.fn();
    render(<EquipmentLearnForm datasets={[DATASET]} datasetId="pump-data" busy={false} t={t} onLearn={learn} />);
    fireEvent.change(screen.getByTestId("learn-start"), { target: { value: "2026-01-01T02:00:00Z" } });
    fireEvent.click(screen.getByTestId("learn-submit"));
    expect(await screen.findByRole("alert")).toHaveTextContent(t("equipmentAnomaly.invalidWindow"));
    expect(learn).not.toHaveBeenCalled();
  });
  it("refreshes the proposed bounds when the dataset changes", () => {
    const second = { ...DATASET, id: "other", time_range: {
      start_utc: "2026-02-01T00:00:00Z", end_utc: "2026-02-01T02:00:00Z",
    } };
    render(<EquipmentLearnForm datasets={[DATASET, second]} datasetId="pump-data" busy={false} t={t} onLearn={vi.fn()} />);
    fireEvent.change(screen.getByTestId("learn-dataset"), { target: { value: "other" } });
    expect(screen.getByTestId("learn-start")).toHaveValue(second.time_range.start_utc);
    expect(screen.getByTestId("learn-end")).toHaveValue(second.time_range.end_utc);
  });
  it("disables submission and editing while the model learns", () => {
    render(<EquipmentLearnForm datasets={[DATASET]} datasetId="pump-data" busy t={t} onLearn={vi.fn()} />);
    expect(screen.getByTestId("learn-submit")).toBeDisabled();
    expect(screen.getByTestId("learn-dataset")).toBeDisabled();
    expect(screen.getByTestId("learn-start")).toBeDisabled();
    expect(screen.getByTestId("learn-end")).toBeDisabled();
  });
  it("displays server failures from the learning action", async () => {
    const learn = vi.fn().mockRejectedValue(new Error("Missing current tag"));
    render(<EquipmentLearnForm datasets={[DATASET]} datasetId="pump-data" busy={false} t={t} onLearn={learn} />);
    fireEvent.click(screen.getByTestId("learn-submit"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Missing current tag");
  });
});

import { within } from "@testing-library/react";
import { EquipmentAnomaliesPage } from "./EquipmentAnomaliesPage";
import type { EquipmentAnomaly, EquipmentEvent } from "../equipmentAnomalyApi";

const permissions = vi.hoisted(() => ({ allowed: true }));
vi.mock("../AuthContext", () => ({ useCan: () => ({ allowed: permissions.allowed, reason: "Permission required" }) }));
vi.mock("./AnomalyPage", () => ({ AnomalyPage: () => <p>Free-tag PCA detector</p> }));
const EVENT: EquipmentEvent = {
  equipment: "pump", opened_utc: "2026-01-01T00:01:00Z", closed_utc: null,
  peak: 2, contributions: [{ tag: "current", share: 0.75 }],
  residuals: [{ tag: "current", z: 2.5, trend: 1 }], loops_affected: ["flow-loop"], outcome: null,
};
const ROW: EquipmentAnomaly = {
  equipment_id: "pump", model_status: "learned", live_state: { status: "anomaly" },
  open_event: EVENT, events: [EVENT], shelved_until_utc: null,
};

/** Install a real JSON transport boundary and let writes update the refreshed server snapshot. */
function worklistResponses(options: { row?: EquipmentAnomaly; empty?: boolean; fail?: boolean } = {}) {
  permissions.allowed = true;
  let row = options.row ?? { ...ROW };
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (options.fail) return new Response(JSON.stringify({ detail: "Equipment store unavailable" }), { status: 503 });
    if (url.endsWith("/shelve") && init?.method === "POST") row = { ...row, shelved_until_utc: JSON.parse(String(init.body)).until_utc };
    if (url.endsWith("/shelve") && init?.method === "DELETE") row = { ...row, shelved_until_utc: null };
    const bodies: Record<string, unknown> = {
      "/api/site": { equipment: options.empty ? [] : [
        { id: "area", name: "Grinding", level: "area" },
        { id: "pump", name: "Feed pump", parent: "area", level: "equipment", criticality: "high" },
      ] },
      "/api/datasets": [DATASET], "/api/equipment/anomalies": [row],
      "/api/equipment/models": [{ equipment_id: "pump", status: row.model_status, variables: ["current"], windows: [[0, 300]] }],
    };
    return new Response(JSON.stringify(bodies[url] ?? {}), { status: 200 });
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

/** Render the equipment landing tab with the application's usual dataset props. */
function renderWorklist() {
  return render(<EquipmentAnomaliesPage datasetId="pump-data" recordHours={1} t={t} />);
}

describe("equipment anomaly worklist", () => {
  it("shows the catalogue area, model state and current signal evidence", async () => {
    worklistResponses(); renderWorklist();
    const card = await screen.findByTestId("equipment-pump");
    expect(screen.getByRole("region", { name: "Grinding" })).toBeInTheDocument();
    expect(within(card).getByRole("heading", { name: "Feed pump" })).toBeInTheDocument();
    expect(within(card).getByRole("status")).toHaveTextContent(t("equipmentAnomaly.model.learned"));
    expect(card).toHaveTextContent("current: 75.0 %");
    expect(card).toHaveTextContent("current: 2.50 σ");
    expect(card).toHaveTextContent("flow-loop");
  });
  it("keeps the previous free-tag detector reachable from Advanced", async () => {
    worklistResponses(); renderWorklist();
    await screen.findByTestId("equipment-pump");
    fireEvent.click(screen.getByRole("button", { name: t("equipmentAnomaly.advanced") }));
    expect(screen.getByText("Free-tag PCA detector")).toBeInTheDocument();
    expect(screen.queryByTestId("equipment-anomalies-page")).not.toBeInTheDocument();
  });
  it("shows an empty catalogue instead of implying healthy equipment", async () => {
    worklistResponses({ empty: true }); renderWorklist();
    expect(await screen.findByText(t("equipmentAnomaly.empty"))).toBeInTheDocument();
    expect(screen.queryByTestId("equipment-pump")).not.toBeInTheDocument();
  });
  it("reports loading failures to the operator", async () => {
    worklistResponses({ fail: true }); renderWorklist();
    expect(await screen.findByRole("alert")).toHaveTextContent("Equipment store unavailable");
  });
  it("shows not-enough-data and stopped states without inventing a current event", async () => {
    worklistResponses({ row: { ...ROW, model_status: "not_enough_data", live_state: { status: "stopped" }, open_event: null, events: [] } });
    renderWorklist();
    const card = await screen.findByTestId("equipment-pump");
    expect(card).toHaveTextContent(t("equipmentAnomaly.model.not_enough_data"));
    expect(card).toHaveTextContent(t("equipmentAnomaly.live.stopped"));
    expect(card).toHaveTextContent(t("equipmentAnomaly.noCurrent"));
    expect(card).toHaveTextContent(t("equipmentAnomaly.noHistory"));
  });
  it("disables learning, shelving and outcomes for a viewer", async () => {
    worklistResponses(); permissions.allowed = false; renderWorklist();
    const card = await screen.findByTestId("equipment-pump");
    expect(within(card).getByRole("button", { name: t("equipmentAnomaly.learn") })).toBeDisabled();
    expect(screen.getByTestId("shelve-submit")).toBeDisabled();
    expect(screen.getByTestId(`outcome-${EVENT.opened_utc}`)).toBeDisabled();
  });
  it("learns the chosen equipment with the complete proposed record", async () => {
    const fetch = worklistResponses(); renderWorklist();
    const card = await screen.findByTestId("equipment-pump");
    fireEvent.click(within(card).getByRole("button", { name: t("equipmentAnomaly.learn") }));
    fireEvent.click(screen.getByTestId("learn-submit"));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/datasets/pump-data/equipment/pump/learn", expect.objectContaining({ method: "POST", body: JSON.stringify({ exclusions: [] }) })));
  });
  it("shelves with an explicit UTC expiry and can unshelve after refresh", async () => {
    const fetch = worklistResponses(); renderWorklist();
    await screen.findByTestId("equipment-pump");
    fireEvent.change(screen.getByTestId("shelve-until"), { target: { value: "2099-01-01T12:00" } });
    fireEvent.click(screen.getByTestId("shelve-submit"));
    fireEvent.click(await screen.findByTestId("unshelve"));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/equipment/pump/shelve", expect.objectContaining({ method: "DELETE" })));
    expect(fetch).toHaveBeenCalledWith("/api/equipment/pump/shelve", expect.objectContaining({ method: "POST", body: JSON.stringify({ until_utc: "2099-01-01T12:00:00.000Z" }) }));
  });
  it("saves feedback against the event's exact opening identity", async () => {
    const fetch = worklistResponses(); renderWorklist();
    await screen.findByTestId("equipment-pump");
    fireEvent.change(screen.getByTestId(`outcome-${EVENT.opened_utc}`), { target: { value: "false_alarm" } });
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(`/api/equipment/events/${encodeURIComponent(EVENT.opened_utc)}/pump/outcome`, expect.objectContaining({ method: "PUT", body: JSON.stringify({ outcome: "false_alarm" }) })));
  });
});

describe("equipment learning progress", () => {
  it("shows learning until the synchronous learn request completes", async () => {
    const fetch = worklistResponses();
    let finishLearning!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => { finishLearning = resolve; });
    const respond = fetch.getMockImplementation()!;
    fetch.mockImplementation((url, init) => url.endsWith("/learn") ? pending : respond(url, init));
    renderWorklist();
    const card = await screen.findByTestId("equipment-pump");
    fireEvent.click(within(card).getByRole("button", { name: t("equipmentAnomaly.learn") }));
    fireEvent.click(screen.getByTestId("learn-submit"));
    await waitFor(() => expect(within(card).getByRole("status")).toHaveTextContent(t("equipmentAnomaly.model.learning")));
    expect(screen.getByTestId("learn-submit")).toBeDisabled();
    finishLearning(new Response("{}"));
    await waitFor(() => expect(screen.getByTestId("learn-submit")).not.toBeDisabled());
  });
});

describe("suppressed equipment scoring", () => {
  it("shows runtime shelving instead of a normal live state", async () => {
    worklistResponses({ row: { ...ROW, live_state: { status: "ok", shelved: true }, open_event: null, events: [] } });
    renderWorklist();
    const card = await screen.findByTestId("equipment-pump");
    expect(card).toHaveTextContent(t("equipmentAnomaly.live.shelved"));
    expect(card).not.toHaveTextContent(`${t("equipmentAnomaly.live")}: ${t("equipmentAnomaly.live.ok")}`);
  });
  it("shows missing good values instead of a normal live state", async () => {
    worklistResponses({ row: { ...ROW, live_state: { status: "ok", reason: "missing_good_values" }, open_event: null, events: [] } });
    renderWorklist();
    const card = await screen.findByTestId("equipment-pump");
    expect(card).toHaveTextContent(t("equipmentAnomaly.live.unavailable"));
    expect(card).not.toHaveTextContent(`${t("equipmentAnomaly.live")}: ${t("equipmentAnomaly.live.ok")}`);
  });
});

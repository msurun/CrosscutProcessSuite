// Verify the equipment anomaly client against the backend route contracts.
// Requests use the shared authenticated transport and preserve server errors.
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import {
  fetchEquipmentAnomalies, fetchEquipmentModels, learnEquipment,
  setEquipmentOutcome, shelveEquipment, unshelveEquipment,
} from "./equipmentAnomalyApi";

/** Install a JSON response and retain the complete request for assertions. */
function stubFetch(body: unknown, status = 200) {
  const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("equipmentAnomalyApi", () => {
  it("returns model summaries including accepted windows", async () => {
    const rows = [{ equipment_id: "pump", status: "learned", windows: [[0, 299]], variables: ["flow"] }];
    const fetchMock = stubFetch(rows);
    expect(await fetchEquipmentModels()).toEqual(rows);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/equipment/models");
  });

  it("returns live equipment rows without discarding event history", async () => {
    const rows = [{ equipment_id: "pump", model_status: "none", events: [], open_event: null }];
    const fetchMock = stubFetch(rows);
    expect(await fetchEquipmentAnomalies()).toEqual(rows);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/equipment/anomalies");
  });

  it("encodes learning identifiers and sends aware exclusion intervals", async () => {
    const model = { status: "learned", windows: [[100, 299]], variables: ["flow"] };
    const fetchMock = stubFetch(model);
    const exclusions: [string, string][] = [["2026-01-01T00:00:00Z", "2026-01-01T00:01:39Z"]];
    expect(await learnEquipment("record/a", "pump:1", exclusions)).toEqual(model);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/datasets/record%2Fa/equipment/pump%3A1/learn");
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "POST", body: JSON.stringify({ exclusions }) });
  });

  it("uses no exclusions when learning the proposed dataset window", async () => {
    const fetchMock = stubFetch({ status: "not_enough_data" });
    await learnEquipment("record", "pump");
    expect(fetchMock.mock.calls[0][1]?.body).toBe(JSON.stringify({ exclusions: [] }));
  });

  it("sends an explicit UTC shelving expiry", async () => {
    const untilUtc = "2030-01-01T00:00:00Z";
    const result = { equipment_id: "pump:1", until_utc: untilUtc };
    const fetchMock = stubFetch(result);
    expect(await shelveEquipment("pump:1", untilUtc)).toEqual(result);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/equipment/pump%3A1/shelve");
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "POST", body: JSON.stringify({ until_utc: untilUtc }) });
  });

  it("removes shelving with DELETE", async () => {
    const result = { equipment_id: "pump", until_utc: null };
    const fetchMock = stubFetch(result);
    expect(await unshelveEquipment("pump")).toEqual(result);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/equipment/pump/shelve");
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "DELETE" });
  });

  it("encodes the event identity and saves an operator outcome", async () => {
    const openedUtc = "2026-01-01T00:00:00+00:00";
    const event = { equipment: "pump", opened_utc: openedUtc, outcome: "false_alarm" };
    const fetchMock = stubFetch(event);
    expect(await setEquipmentOutcome(openedUtc, "pump", "false_alarm")).toEqual(event);
    expect(fetchMock.mock.calls[0][0]).toBe(`/api/equipment/events/${encodeURIComponent(openedUtc)}/pump/outcome`);
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "PUT", body: JSON.stringify({ outcome: "false_alarm" }) });
  });

  it("preserves actionable learning errors from the backend", async () => {
    stubFetch({ detail: "Missing tag 'flow'; include it in the dataset" }, 422);
    await expect(learnEquipment("record", "pump")).rejects.toMatchObject({
      status: 422, message: "Missing tag 'flow'; include it in the dataset",
    });
  });

  it("reports unavailable live state as an API error", async () => {
    stubFetch({ detail: "equipment events unavailable" }, 503);
    await expect(fetchEquipmentAnomalies()).rejects.toBeInstanceOf(ApiError);
  });

  it("preserves denied operator action errors", async () => {
    stubFetch({ detail: "permission denied" }, 403);
    await expect(unshelveEquipment("pump")).rejects.toMatchObject({ status: 403 });
  });
});

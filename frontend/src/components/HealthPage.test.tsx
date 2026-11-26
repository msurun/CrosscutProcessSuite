/**
 * Unit tests for the Health page (#170): items with status and reason, refresh, the log export
 * for a user manager, and its refusal for a viewer. The API client is mocked.
 */

import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as healthApi from "../healthApi";
import { renderAs, mockT } from "../tuningTestKit";
import { detailLines, durationText, itemLabel, itemReason } from "./healthFormat";
import { HealthPage } from "./HealthPage";

const report: healthApi.HealthReport = {
  generated_utc: "2026-11-26T12:00:00+00:00",
  status: "error",
  items: [
    { id: "runtime", group: "runtime", status: "ok", code: "runtime_running", reason: "The runtime is running.",
      details: { uptime_s: 7500, updated_age_s: 2 } },
    { id: "job:j1", group: "jobs", status: "error", code: "job_error", reason: "The last run failed: boom.",
      details: { last_error: "boom", last_error_utc: "2026-11-26T11:59:00+00:00", overrun_count: 2, lag_s: 4 } },
    { id: "gateway", group: "gateway", status: "warning", code: "gateway_mode_off", reason: "The gateway mode is off.",
      details: { mode: "off" } },
    { id: "liveness:controller:C1", group: "liveness", status: "error", code: "liveness_lost", reason: "lost",
      details: { age_s: 400 } },
    { id: "disk", group: "system", status: "ok", code: "disk_ok", reason: "Enough free space.",
      details: { free_bytes: 50 * 2 ** 30, total_bytes: 100 * 2 ** 30 } },
  ],
};

describe("healthFormat", () => {
  it("labels jobs and controllers with their name and formats durations", () => {
    expect(itemLabel(report.items[1], mockT)).toBe('health.label.job{"id":"j1"}');
    expect(itemLabel(report.items[3], mockT)).toBe('health.label.controller{"id":"C1"}');
    expect(durationText(7500)).toBe("2 h 5 min");
    expect(durationText(45)).toBe("45 s");
  });

  it("falls back to the server reason when a code has no translation", () => {
    const unknown = { ...report.items[0], code: "brand_new" };
    const identity = (key: string) => key;
    expect(itemReason(unknown, identity)).toBe("The runtime is running.");
  });

  it("lists uptime for the runtime and free space for the disk", () => {
    expect(detailLines(report.items[0], mockT)).toContain("health.detail.uptime: 2 h 5 min");
    expect(detailLines(report.items[4], mockT)).toContain("health.detail.free: 50.0 / 100.0 GiB");
  });
});

describe("HealthPage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows every item with its status and the worst overall status", async () => {
    vi.spyOn(healthApi, "fetchHealth").mockResolvedValue(report);
    await renderAs("viewer", <HealthPage t={mockT} />, "viewer", "health-page");
    expect(await screen.findByTestId("health-item-job:j1")).toHaveTextContent("health.status.error");
    expect(screen.getByTestId("health-item-job:j1")).toHaveTextContent("health.detail.overruns: 2");
    expect(screen.getByTestId("health-item-gateway")).toHaveTextContent("health.status.warning");
    expect(screen.getByTestId("health-item-runtime")).toHaveTextContent("health.status.ok");
    expect(screen.getByTestId("health-overall")).toHaveTextContent("health.overall.error");
  });

  it("reads again on Refresh and shows a failure as an alert", async () => {
    const fetchHealth = vi.spyOn(healthApi, "fetchHealth").mockResolvedValue(report);
    await renderAs("viewer", <HealthPage t={mockT} />, "viewer", "health-page");
    await screen.findByTestId("health-item-runtime");
    fetchHealth.mockRejectedValue(new healthApi.HealthApiError(500, "down"));
    fireEvent.click(screen.getByTestId("health-refresh"));
    expect(await screen.findByTestId("health-error")).toHaveTextContent("down");
  });

  it("exports the logs of the chosen range for a user manager", async () => {
    vi.spyOn(healthApi, "fetchHealth").mockResolvedValue(report);
    const exportLogs = vi.spyOn(healthApi, "fetchLogExport").mockResolvedValue(new Blob(["zip"]));
    const save = vi.spyOn(healthApi, "saveBlob").mockImplementation(() => undefined);
    await renderAs("admin", <HealthPage t={mockT} />, "admin", "health-page");
    fireEvent.change(screen.getByTestId("health-export-start"), { target: { value: "2026-11-26T10:00" } });
    fireEvent.change(screen.getByTestId("health-export-end"), { target: { value: "2026-11-26T11:00" } });
    fireEvent.click(screen.getByTestId("health-export-button"));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    const [start, end] = exportLogs.mock.calls[0];
    expect(new Date(start).getTime()).toBe(new Date("2026-11-26T10:00").getTime());
    expect(new Date(end).getTime()).toBe(new Date("2026-11-26T11:00").getTime());
  });

  it("does not export for a viewer and explains why", async () => {
    vi.spyOn(healthApi, "fetchHealth").mockResolvedValue(report);
    const exportLogs = vi.spyOn(healthApi, "fetchLogExport").mockResolvedValue(new Blob(["zip"]));
    await renderAs("viewer", <HealthPage t={mockT} />, "viewer", "health-page");
    const button = screen.getByTestId("health-export-button");
    expect(button).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(button);
    expect(exportLogs).not.toHaveBeenCalled();
  });

  it("shows the server refusal of an export", async () => {
    vi.spyOn(healthApi, "fetchHealth").mockResolvedValue(report);
    vi.spyOn(healthApi, "fetchLogExport").mockRejectedValue(new healthApi.HealthApiError(422, "bad range"));
    await renderAs("admin", <HealthPage t={mockT} />, "admin", "health-page");
    fireEvent.click(screen.getByTestId("health-export-button"));
    expect(await screen.findByTestId("health-export-error")).toHaveTextContent("bad range");
  });
});

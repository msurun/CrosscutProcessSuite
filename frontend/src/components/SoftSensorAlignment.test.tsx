// Behaviour tests for physical-delay scans and their uncertainty display.
// Stub HTTP so the UI contract is checked independently of numerical fitting.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { translate } from "../i18n";
import { SoftSensorAlignment } from "./SoftSensorAlignment";

const translateEnglish = (key: string, values?: Record<string, string | number>) => translate("en", key, values);
const RESULT = { best_delay_s: 120, interval_low_s: 60, interval_high_s: 180, method: "bootstrap", profile: [{ delay_s: 120, correlation: 0.98 }] };

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

/** Fill the required reference and submit the scan. */
function submitScan() {
  fireEvent.change(screen.getByLabelText("Reference tag"), { target: { value: "online.quality" } });
  fireEvent.click(screen.getByRole("button", { name: "Scan delays" }));
}

it("sends the user range and displays the optimum with its uncertainty and profile", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(RESULT)));
  vi.stubGlobal("fetch", fetchMock);
  render(<SoftSensorAlignment datasetId="dataset" sensorId="sensor" t={translateEnglish} />);
  fireEvent.change(screen.getByLabelText("Minimum delay (s)"), { target: { value: "0" } });
  submitScan();
  expect(await screen.findByTestId("alignment-result")).toHaveTextContent("Best delay: 120 s; uncertainty interval: 60 to 180 s.");
  expect(fetchMock.mock.calls[0][0]).toBe("/api/datasets/dataset/softsensor/sensor/alignment-scan");
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ reference_tag: "online.quality", min_delay_s: 0, max_delay_s: 3600, step_s: 60 });
  fireEvent.click(screen.getByText("Correlation profile", { selector: "summary" }));
  expect(screen.getByRole("cell", { name: "0.980" })).toBeVisible();
});

it("shows the server explanation when a scan cannot be estimated", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "No common finite samples; widen the range." }), { status: 422 })));
  render(<SoftSensorAlignment datasetId="dataset" sensorId="sensor" t={translateEnglish} />);
  submitScan();
  expect(await screen.findByRole("alert")).toHaveTextContent("No common finite samples; widen the range.");
  expect(screen.queryByTestId("alignment-result")).toBeNull();
});

it("provides translated scan controls in Spanish and Polish", () => {
  expect(translate("es", "soft.alignment.scan")).toBe("Explorar retardos");
  expect(translate("pl", "soft.alignment.scan")).toBe("Skanuj opóźnienia");
});

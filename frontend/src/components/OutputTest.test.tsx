// Verify deliberate confirmation, authenticated command payloads and cancellation.
// Plant-side safety belongs to the gateway and is covered by Python tests.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { translate } from "../i18n";
import { OutputTest } from "./OutputTest";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const t = (key: string) => translate("en", key);

/** Fill an explicit signed step without accepting any implicit bounds. */
function fillFields() {
  fireEvent.change(screen.getByLabelText("Gateway OUT target"), { target: { value: "FIC.OUT" } });
  fireEvent.change(screen.getByLabelText("Signed amplitude (OUT engineering units)"),
    { target: { value: "-1" } });
  fireEvent.change(screen.getByLabelText("Duration (seconds)"), { target: { value: "5" } });
}

it("requires explicit values before the human confirms the test", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ reason_code: "out_step_started" })));
  vi.stubGlobal("fetch", fetch);
  render(<OutputTest t={t} />);
  expect(screen.getByRole("button", { name: "Confirm and start OUT test" })).toBeDisabled();
  fillFields();
  fireEvent.click(screen.getByRole("button", { name: "Confirm and start OUT test" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ target: "FIC.OUT", amplitude: -1, duration_s: 5 });
});

it("offers restoration even after a browser reload without a local running test", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ reason_code: "restored" })));
  vi.stubGlobal("fetch", fetch);
  render(<OutputTest t={t} />);
  fireEvent.change(screen.getByLabelText("Gateway OUT target"), { target: { value: "FIC.OUT" } });
  fireEvent.click(screen.getByRole("button", { name: "Cancel / restore pre-test OUT" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/gateway/output-tests/FIC.OUT/cancel", expect.anything()));
});

it.each(["en", "pl", "es"])("shows translated safety text in %s", (language) => {
  render(<OutputTest t={(key) => translate(language, key)} />);
  expect(screen.getByRole("heading")).toHaveTextContent(translate(language, "outTest.title"));
  expect(screen.getByText(translate(language, "outTest.notice"))).toHaveTextContent("MAN");
});

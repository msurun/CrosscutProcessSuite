// Module view integration tests use the real HTTP helpers.
// An isolated server keeps stored documents separate from unsaved form edits.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { ReactElement } from "react";
import { translate } from "../i18n";
import type { JsonDocument } from "../schemaFormModel";
import { AdvisoryPage } from "./AdvisoryPage";
import { AnomalyPage } from "./AnomalyPage";
import { SoftSensorPage } from "./SoftSensorPage";
import supervisor from "../../../supervisor/examples/mill_feed_advisor.json";
import anomaly from "../../../anomaly/examples/mill_circuit_pca.json";
import softsensor from "../../../softsensor/examples/mill_circuit_pls.json";
import supervisorSchema from "../../../schemas/supervisor.schema.json";
import anomalySchema from "../../../schemas/anomaly.schema.json";
import softsensorSchema from "../../../schemas/softsensor.schema.json";

const t = (key: string, params?: Record<string, string | number>) => translate("en", key, params);
const schemas: Record<string, unknown> = { supervisor: supervisorSchema, anomaly: anomalySchema, softsensor: softsensorSchema };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

/** Build an HTTP response for the module's schema, saved document and empty model. */
function moduleResponse(kind: string, store: { document: JsonDocument }, input: string, options?: RequestInit) {
  const route = kind === "supervisor" ? "supervisors" : kind;
  const url = `/api/${route}/${store.document.id}`;
  let body: unknown = { detail: "model not fitted" };
  let status = 200;
  if (input === `/api/schemas/${kind}`) body = schemas[kind];
  else if (input === `/api/${route}`) body = [store.document.id];
  else if (input === url && options?.method === "PUT") {
    const document = JSON.parse(String(options.body));
    status = document.id === store.document.id ? 200 : 422;
    body = status === 200 ? (store.document = document) : { detail: ["id: does not match selected configuration"] };
  } else if (input === url) body = store.document;
  else if (input.endsWith("/log")) body = { records: [], total: 0, chain: { ok: true, records: 0 } };
  else status = 404;
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/** Keep the stored document separate from unsaved form edits. */
function serveModule(kind: string, initial: JsonDocument) {
  const store = { document: { ...initial } };
  const route = kind === "supervisor" ? "supervisors" : kind;
  const fetch = vi.fn(async (input: string, options?: RequestInit) => moduleResponse(kind, store, input, options));
  vi.stubGlobal("fetch", fetch);
  return { fetch, url: `/api/${route}/${initial.id}` };
}

/** Prove that save persists and reload discards a later unsaved edit. */
// Generous waits: the round trip (save, then reload) is slow when the full suite runs on a loaded
// machine; the default 1 s of findBy/waitFor made this test flaky (#259).
const SLOW = { timeout: 10_000 };

async function verifyRoundTrip(view: ReactElement, kind: string, document: JsonDocument) {
  const server = serveModule(kind, document);
  render(view);
  const editor = within(await screen.findByRole("region", { name: "Configuration" }, SLOW));
  fireEvent.change(editor.getByLabelText("description"), { target: { value: "Persisted description" } });
  fireEvent.click(editor.getByRole("button", { name: /^Save$/ }));
  await editor.findByText("Saved.", {}, SLOW);
  expect(server.fetch).toHaveBeenCalledWith(server.url, expect.objectContaining({ method: "PUT" }));
  fireEvent.change(editor.getByLabelText("description"), { target: { value: "Discard me" } });
  fireEvent.click(editor.getByRole("button", { name: "Reload" }));
  await waitFor(() => expect(screen.getByLabelText("description")).toHaveValue("Persisted description"), SLOW);
}

/** Prove that rejected documents show validation without a success message. */
async function verifyValidation(view: ReactElement, kind: string, document: JsonDocument) {
  serveModule(kind, document);
  render(view);
  const editor = within(await screen.findByRole("region", { name: "Configuration" }));
  fireEvent.change(editor.getByLabelText("id *"), { target: { value: "wrong_id" } });
  fireEvent.click(editor.getByRole("button", { name: /^Save$/ }));
  expect(await editor.findByRole("alert")).toHaveTextContent("does not match");
  expect(editor.queryByText("Saved.")).not.toBeInTheDocument();
}

it("saves and reloads supervisor configuration in the Advisory view", async () => {
  await verifyRoundTrip(<AdvisoryPage datasetId="" t={t} />, "supervisor", supervisor);
}, 30_000);
it("saves and reloads detector configuration in the Anomaly view", async () => {
  await verifyRoundTrip(<AnomalyPage datasetId="" recordHours={null} t={t} />, "anomaly", anomaly);
});
it("saves and reloads sensor configuration in the Soft sensor view", async () => {
  await verifyRoundTrip(<SoftSensorPage datasetId="" recordHours={null} startUtc="" t={t} />, "softsensor", softsensor);
});
it("shows supervisor validation in the Advisory view", async () => {
  await verifyValidation(<AdvisoryPage datasetId="" t={t} />, "supervisor", supervisor);
});
it("shows detector validation in the Anomaly view", async () => {
  await verifyValidation(<AnomalyPage datasetId="" recordHours={null} t={t} />, "anomaly", anomaly);
});
it("shows sensor validation in the Soft sensor view", async () => {
  await verifyValidation(<SoftSensorPage datasetId="" recordHours={null} startUtc="" t={t} />, "softsensor", softsensor);
});
it("shows the advanced bias correction section in the Soft sensor editor", async () => {
  serveModule("softsensor", softsensor);
  render(<SoftSensorPage datasetId="" recordHours={null} startUtc="" t={t} />);
  const editor = within(await screen.findByRole("region", { name: "Configuration" }));
  expect(await editor.findByTestId("schema-object-bias_correction")).toBeInTheDocument();
  expect(editor.getByLabelText("weight")).toBeInTheDocument();
  expect(editor.getByText(/does not prove that the model beats lab persistence/)).toBeInTheDocument();
});

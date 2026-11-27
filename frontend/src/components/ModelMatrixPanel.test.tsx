// Verify matrix edits preserve fit evidence and create an audited new version.
// HTTP fixtures model both immutable parents and visible server refusals.
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { translate } from "../i18n";
import type { IdentModelVersion } from "../mpcModelApi";
import { ModelMatrixPanel } from "./ModelMatrixPanel";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const t = (key: string, params?: Record<string, string | number>) => translate("en", key, params);
const PARENT: IdentModelVersion = { model_id: "base", sha256: "a".repeat(64), cycle_s: 1,
  input_names: ["MV", "DV"], cv_names: ["CV"], pairs: [
    { input_name: "MV", cv_name: "CV", gain: 2, time_constant_s: 10, dead_time_s: 2, enabled: true,
      quality: { passed: true, free_run_r2: 0.9, excitation_events: 3, reasons: [] } },
    { input_name: "DV", cv_name: "CV", gain: -1, time_constant_s: 5, dead_time_s: 0, enabled: true,
      quality: { passed: false, free_run_r2: 0.2, excitation_events: 1, reasons: ["weak excitation"] } },
  ] };

/** Open a parent matrix without any automatic background write. */
async function openModel() {
  render(<ModelMatrixPanel t={t} />);
  fireEvent.change(screen.getByLabelText("Model artifact id"), { target: { value: "base" } });
  fireEvent.click(screen.getByRole("button", { name: "Load model" }));
  return screen.findByRole("table");
}

/** Edit one parameter using its path-specific label. */
function change(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

it("renders an input by CV grid with quality verdicts and signed step responses", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(PARENT)));
  vi.stubGlobal("fetch", fetch);
  const table = await openModel();
  expect(within(table).getAllByRole("row")).toHaveLength(3);
  expect(table).toHaveTextContent("Quality gate failed");
  expect(table).toHaveTextContent("weak excitation");
  expect(screen.getByLabelText("Gain MV → CV")).toHaveValue(2);
  expect(screen.getAllByRole("img")).toHaveLength(2);
  expect(screen.getByRole("button", { name: "Save as new version" })).toBeDisabled();
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("requires an author and meaningful reason then saves a complete changed copy with parent hash", async () => {
  const child = { ...PARENT, model_id: "child", sha256: "b".repeat(64), parent_model_id: "base",
    parent_sha256: PARENT.sha256, author: "Engineer", reason: "Checked step test",
    pairs: [{ ...PARENT.pairs[0], gain: 3 }, { ...PARENT.pairs[1], enabled: false }] };
  const fetch = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(PARENT)))
    .mockResolvedValueOnce(new Response(JSON.stringify(child)));
  vi.stubGlobal("fetch", fetch); await openModel();
  change("Gain MV → CV", "3");
  fireEvent.click(screen.getByLabelText("Enabled DV → CV"));
  expect(screen.getByText("Gain: Parent: 2; edited: 3")).toBeInTheDocument();
  change("Author", "Engineer"); change("Reason for the new version", "   ");
  expect(screen.getByRole("button", { name: "Save as new version" })).toBeDisabled();
  change("Reason for the new version", "Checked step test");
  fireEvent.click(screen.getByRole("button", { name: "Save as new version" }));
  expect(await screen.findByText("Saved new model version child")).toHaveAttribute("role", "status");
  expect(fetch.mock.calls[1][0]).toBe("/api/mpc/models/base/versions");
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ parent_sha256: PARENT.sha256,
    author: "Engineer", reason: "Checked step test", pairs: child.pairs.map(({ quality: _quality, ...pair }) => pair) });
  expect(PARENT.pairs[0].gain).toBe(2);
  expect(screen.getByText("weak excitation")).toBeInTheDocument();
});

it("refuses invalid time constants and blank gains before saving", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(PARENT))));
  await openModel(); change("Author", "Engineer"); change("Reason for the new version", "Review");
  change("Time constant (s) MV → CV", "0");
  expect(screen.getByRole("button", { name: "Save as new version" })).toBeDisabled();
  expect(screen.getAllByRole("img")).toHaveLength(1);
  change("Time constant (s) MV → CV", "5"); change("Gain MV → CV", "");
  expect(screen.getByRole("button", { name: "Save as new version" })).toBeDisabled();
});

it("shows a tampered-parent refusal and preserves the draft for inspection", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(PARENT)))
    .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Parent integrity mismatch" }), { status: 409 })));
  await openModel(); change("Gain MV → CV", "4"); change("Author", "Engineer");
  change("Reason for the new version", "Review");
  fireEvent.click(screen.getByRole("button", { name: "Save as new version" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Parent integrity mismatch");
  expect(screen.getByLabelText("Gain MV → CV")).toHaveValue(4);
});

it("shows load permission errors without displaying an unverified grid", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "forbidden" }), { status: 403 })));
  render(<ModelMatrixPanel t={t} />);
  change("Model artifact id", "base"); fireEvent.click(screen.getByRole("button", { name: "Load model" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("forbidden");
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});

it.each(["en", "pl", "es"])("translates the complete loaded editor in %s with real diacritics", async (language) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(PARENT))));
  const messages = (key: string, params?: Record<string, string | number>) => translate(language, key, params);
  render(<ModelMatrixPanel t={messages} />);
  fireEvent.change(screen.getByLabelText(messages("modelMatrix.modelId")), { target: { value: "base" } });
  fireEvent.click(screen.getByRole("button", { name: messages("modelMatrix.load") }));
  await screen.findByRole("table");
  const panel = screen.getByRole("region", { name: messages("modelMatrix.title") });
  expect(panel.textContent).not.toContain("?");
  expect(panel.textContent).not.toContain("modelMatrix.");
});

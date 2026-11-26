// Tests for CatalogueFromSource: preset to preview, instant re-test without browsing, checkbox defaults,
// import payload and added counts, and the error alert. The clients are mocked; t returns the key.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api";
import * as api from "../catalogueSourceApi";
import * as sources from "../sourcesApi";
import { CatalogueFromSource } from "./CatalogueFromSource";
import { moveItem, parseRoles } from "./CatalogueRulesEditor";

vi.mock("../catalogueSourceApi");
vi.mock("../sourcesApi");

const t = (key: string, vars?: Record<string, string | number>) => (vars ? `${key} ${JSON.stringify(vars)}` : key);

const naming: api.NamingResult = {
  matches: [{ tag: "FIC101.PV", rule: 0, loop: "FIC101", role: "pv" }],
  unmatched: ["XYZ"],
  conflicts: [],
  loops: { FIC101: { pv: "FIC101.PV" } },
  incomplete: [{ loop: "FIC101", missing: ["out"] }],
  tree: { A1: { P1: { loops: ["FIC101"], signals: [] } } },
};
const preview: api.CataloguePreview = {
  items: [{ name: "FIC101.PV" }, { name: "XYZ" }],
  truncated: true,
  naming,
};

async function openPreview() {
  render(<CatalogueFromSource t={t} />);
  await screen.findByRole("option", { name: "pi" });
  fireEvent.change(screen.getByLabelText("catalogueSource.stepSource"), { target: { value: "pi" } });
  fireEvent.change(screen.getByLabelText("catalogueSource.preset"), { target: { value: "isa" } });
  fireEvent.click(screen.getByRole("button", { name: "catalogueSource.preview" }));
  await screen.findByText("catalogueSource.truncated");
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(sources.listSources).mockResolvedValue({ sources: [{ id: "pi", driver: "csv" }] });
  vi.mocked(api.fetchNamingPresets).mockResolvedValue({ isa: [{ pattern: "^(?P<loop>.+)\\.PV$", roles: { PV: "pv" } }] });
  vi.mocked(api.previewCatalogue).mockResolvedValue(preview);
});

describe("CatalogueFromSource", () => {
  it("loads a preset, previews and shows loops, gaps, unmatched and defaults", async () => {
    await openPreview();
    expect(api.previewCatalogue).toHaveBeenCalledWith("pi", [{ pattern: "^(?P<loop>.+)\\.PV$", roles: { PV: "pv" } }]);
    expect(screen.getByTestId("loop-FIC101").querySelector("[data-missing]")?.textContent).toBe("catalogueSource.missing");
    expect(screen.getByText("A1")).toBeTruthy();
    const boxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
    expect(boxes[0].checked).toBe(true);
    expect(boxes[1].checked).toBe(false);
  });

  it("re-tests the browsed names without browsing again", async () => {
    vi.mocked(api.testNamingRules).mockResolvedValue({ ...naming, unmatched: [] });
    await openPreview();
    fireEvent.change(screen.getByLabelText("catalogueSource.rulePattern 1"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "catalogueSource.retest" }));
    await waitFor(() => expect(api.testNamingRules).toHaveBeenCalledWith([{ pattern: "x", roles: { PV: "pv" } }], ["FIC101.PV", "XYZ"]));
    expect(api.previewCatalogue).toHaveBeenCalledTimes(1);
  });

  it("imports the checked items and shows the added counts", async () => {
    vi.mocked(api.importCatalogue).mockResolvedValue({ added: { tags: 1, loops: 1, equipment: 0 } });
    await openPreview();
    fireEvent.click(screen.getByLabelText("catalogueSource.createEquipment"));
    fireEvent.click(screen.getByRole("button", { name: /catalogueSource.import/ }));
    await screen.findByText(/catalogueSource.added/);
    expect(api.importCatalogue).toHaveBeenCalledWith("pi", [{ name: "FIC101.PV" }], expect.any(Array), {
      loops: true,
      equipment: false,
    });
  });

  it("shows an ApiError message in an alert", async () => {
    vi.mocked(api.previewCatalogue).mockRejectedValue(new ApiError(502, "source down"));
    render(<CatalogueFromSource t={t} />);
    await screen.findByRole("option", { name: "pi" });
    fireEvent.change(screen.getByLabelText("catalogueSource.stepSource"), { target: { value: "pi" } });
    fireEvent.click(screen.getByRole("button", { name: "catalogueSource.preview" }));
    expect((await screen.findByRole("alert")).textContent).toBe("source down");
  });
});

describe("rule helpers", () => {
  it("parses value=role lines and skips bad ones", () => {
    expect(parseRoles("PV=pv\n\nbad\nSP = sp \n=x")).toEqual({ PV: "pv", SP: "sp" });
  });

  it("moves items and ignores out-of-range moves", () => {
    expect(moveItem([1, 2, 3], 0, 1)).toEqual([2, 1, 3]);
    expect(moveItem([1, 2], 0, -1)).toEqual([1, 2]);
  });
});

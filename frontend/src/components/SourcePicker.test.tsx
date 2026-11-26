// Tests for SourcePicker: tag filtering by source, search, select all, load call and error display.
// The sources client is mocked; t returns the key so assertions do not depend on a language.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api";
import * as api from "../sourcesApi";
import { SourcePicker } from "./SourcePicker";

vi.mock("../sourcesApi", () => ({ listSources: vi.fn(), fetchSiteTags: vi.fn(), loadHistory: vi.fn() }));

const t = (key: string, vars?: Record<string, string | number>) => (vars ? `${key} ${JSON.stringify(vars)}` : key);
const RESULT = { dataset_id: "d1", cached: true, time_range: { start_utc: "a", end_utc: "b" }, tags: ["A1"] };

beforeEach(() => {
  vi.mocked(api.listSources).mockResolvedValue({ sources: [{ id: "pi", driver: "pi" }, { id: "empty", driver: "x" }] });
  vi.mocked(api.fetchSiteTags).mockResolvedValue([
    { id: "A1", name: "Feed flow", source: "pi" },
    { id: "B2", description: "Level", source: "pi" },
    { id: "C3", source: "other" },
  ]);
  vi.mocked(api.loadHistory).mockResolvedValue(RESULT);
});

async function renderPicker(onLoaded = vi.fn()) {
  render(<SourcePicker t={t} onLoaded={onLoaded} />);
  await screen.findByRole("option", { name: "pi" });
  return onLoaded;
}

describe("SourcePicker", () => {
  it("shows only the tags of the chosen source and filters by search", async () => {
    await renderPicker();
    fireEvent.change(screen.getByLabelText("sourcePicker.source"), { target: { value: "pi" } });
    expect(screen.getByText(/A1/)).toBeTruthy();
    expect(screen.queryByText(/C3/)).toBeNull();
    fireEvent.change(screen.getByLabelText("sourcePicker.search"), { target: { value: "level" } });
    expect(screen.queryByText(/A1/)).toBeNull();
    expect(screen.getByText(/B2/)).toBeTruthy();
  });

  it("keeps Load disabled until tags are selected, then loads and reports", async () => {
    const onLoaded = await renderPicker();
    const load = screen.getByRole("button", { name: "sourcePicker.load" });
    expect((load as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("sourcePicker.source"), { target: { value: "pi" } });
    fireEvent.click(screen.getByRole("button", { name: "sourcePicker.selectAll" }));
    fireEvent.click(load);
    await waitFor(() => expect(onLoaded).toHaveBeenCalledWith(RESULT));
    expect(vi.mocked(api.loadHistory).mock.calls[0][0]).toBe("pi");
    expect(vi.mocked(api.loadHistory).mock.calls[0][1]).toEqual(["A1", "B2"]);
    expect(screen.getAllByRole("status").some((el) => el.textContent === "sourcePicker.cached")).toBe(true);
  });

  it("shows the hint for a source without catalogue tags", async () => {
    await renderPicker();
    fireEvent.change(screen.getByLabelText("sourcePicker.source"), { target: { value: "empty" } });
    expect(screen.getByText("sourcePicker.noTags")).toBeTruthy();
  });

  it("shows an ApiError message in an alert", async () => {
    vi.mocked(api.loadHistory).mockRejectedValue(new ApiError(502, "source down"));
    await renderPicker();
    fireEvent.change(screen.getByLabelText("sourcePicker.source"), { target: { value: "pi" } });
    fireEvent.click(screen.getByRole("button", { name: "sourcePicker.selectAll" }));
    fireEvent.click(screen.getByRole("button", { name: "sourcePicker.load" }));
    expect((await screen.findByRole("alert")).textContent).toBe("source down");
  });
});

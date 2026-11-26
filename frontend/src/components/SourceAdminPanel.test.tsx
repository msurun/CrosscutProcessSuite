// Tests for SourceAdminPanel: list, add opens the form, delete 409 lists the tags, test shows capabilities.
// The client is mocked; t returns the key so assertions do not depend on a language.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../sourceAdminApi";
import { SourceAdminPanel } from "./SourceAdminPanel";

vi.mock("../sourceAdminApi", async () => {
  const actual = await vi.importActual<typeof import("../sourceAdminApi")>("../sourceAdminApi");
  return {
    ...actual,
    listSourceEntries: vi.fn(),
    deleteSource: vi.fn(),
    testSavedSource: vi.fn(),
    fetchSecretStored: vi.fn(),
  };
});

const t = (key: string, vars?: Record<string, string | number>) => (vars ? `${key} ${JSON.stringify(vars)}` : key);

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.listSourceEntries).mockResolvedValue({ sources: [{ id: "pi", driver: "csv" }] });
  vi.mocked(api.fetchSecretStored).mockResolvedValue(false);
});

describe("SourceAdminPanel", () => {
  it("lists sources and opens the form for Add", async () => {
    render(<SourceAdminPanel t={t} />);
    await screen.findByText("pi");
    fireEvent.click(screen.getByRole("button", { name: "sources.add" }));
    expect(screen.getByRole("form", { name: "sources.formTitle" })).toBeTruthy();
  });

  it("shows the tags that block a delete", async () => {
    vi.mocked(api.deleteSource).mockRejectedValue(new api.SourceInUseError(["T1", "T2"]));
    render(<SourceAdminPanel t={t} />);
    await screen.findByText("pi");
    fireEvent.click(screen.getByRole("button", { name: "sources.delete" }));
    expect((await screen.findByRole("alert")).textContent).toContain("T1, T2");
  });

  it("deletes and reloads, and tests a saved source", async () => {
    vi.mocked(api.deleteSource).mockResolvedValue();
    vi.mocked(api.testSavedSource).mockResolvedValue({ status: "ok", capabilities: ["history"] });
    render(<SourceAdminPanel t={t} />);
    await screen.findByText("pi");
    fireEvent.click(screen.getByRole("button", { name: "sources.test" }));
    expect((await screen.findByRole("alert")).textContent).toContain("history");
    fireEvent.click(screen.getByRole("button", { name: "sources.delete" }));
    await waitFor(() => expect(api.listSourceEntries).toHaveBeenCalledTimes(2));
  });
});

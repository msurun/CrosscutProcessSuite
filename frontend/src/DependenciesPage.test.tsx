// frontend/src/DependenciesPage.test.tsx
/** Tests for the Dependencies page and its client: the stale list, the re-confirm note rule and the API calls. */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { API_PREFIX } from "./api";
import { useCan } from "./AuthContext";
import { DependenciesPage } from "./DependenciesPage";
import { confirmDependency, fetchDependencies, type DependencyList } from "./dependenciesApi";

vi.mock("./AuthContext", () => ({ useCan: vi.fn() }));
vi.mock("./dependenciesApi", async (original) => ({
  ...(await original<typeof import("./dependenciesApi")>()),
  fetchDependencies: vi.fn(),
  confirmDependency: vi.fn(),
}));

const t = (key: string, params?: Record<string, string | number>) =>
  params ? `${key} ${JSON.stringify(params)}` : key;

const LIST: DependencyList = {
  published_version: 2,
  tracked: 3,
  items: [{
    key: "anomaly:m1", kind: "anomaly", id: "m1", built_on_version: 1, stale_since_version: 2,
    needs_relearn: true, actions: ["relearn", "reconfirm"],
    reasons: [{ tag: "A", kind: "unit_changed", detail: "'t/h' -> 'kg/h'" }],
  }],
};

beforeEach(() => {
  vi.mocked(useCan).mockReturnValue({ allowed: true, reason: "" });
  vi.mocked(fetchDependencies).mockResolvedValue(LIST);
  vi.mocked(confirmDependency).mockResolvedValue(undefined);
});
afterEach(() => vi.clearAllMocks());

describe("DependenciesPage", () => {
  it("lists the reason and the relearn action of a stale model", async () => {
    render(<DependenciesPage t={t} />);
    const row = await screen.findByTestId("dependency-anomaly:m1");
    expect(row).toHaveTextContent("dependencies.reason.unit_changed");
    expect(row).toHaveTextContent("dependencies.action.relearn");
  });

  it("says nothing is stale when the list is empty", async () => {
    vi.mocked(fetchDependencies).mockResolvedValue({ ...LIST, items: [] });
    render(<DependenciesPage t={t} />);
    expect(await screen.findByTestId("dependencies-clean")).toBeInTheDocument();
  });

  it("keeps re-confirm disabled until a note is typed, then sends it", async () => {
    render(<DependenciesPage t={t} />);
    const button = await screen.findByText("dependencies.reconfirm");
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText("dependencies.note"), { target: { value: "checked" } });
    expect(button).toBeEnabled();
    fireEvent.click(button);
    await waitFor(() => expect(confirmDependency).toHaveBeenCalledWith("anomaly:m1", "checked"));
  });

  it("disables re-confirm without config.edit", async () => {
    vi.mocked(useCan).mockReturnValue({ allowed: false, reason: "no" });
    render(<DependenciesPage t={t} />);
    fireEvent.change(await screen.findByLabelText("dependencies.note"), { target: { value: "x" } });
    expect(screen.getByText("dependencies.reconfirm")).toBeDisabled();
  });

  it("shows a load failure", async () => {
    vi.mocked(fetchDependencies).mockRejectedValue(new Error("boom"));
    render(<DependenciesPage t={t} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
  });
});

describe("dependencies client", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("posts the key and the note to the confirm route", async () => {
    const real = await vi.importActual<typeof import("./dependenciesApi")>("./dependenciesApi");
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, statusText: "OK", headers: new Headers(), json: () => Promise.resolve({}) });
    vi.stubGlobal("fetch", fetchMock);
    await real.confirmDependency("job:kpi", "fine");
    expect(fetchMock.mock.calls[0][0]).toBe(`${API_PREFIX}/dependencies/confirm`);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({ key: "job:kpi", note: "fine" });
  });

  it("maps an error response to the server detail", async () => {
    const real = await vi.importActual<typeof import("./dependenciesApi")>("./dependenciesApi");
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 404, statusText: "Not Found", headers: new Headers(), json: () => Promise.resolve({ detail: "unknown dependent" }) });
    vi.stubGlobal("fetch", fetchMock);
    await expect(real.fetchDependencies()).rejects.toThrow("unknown dependent");
  });
});

// Tests of the shared-link reload: a missing dataset with a plant window calls loadHistory (mocked) once.
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DatasetSummary } from "./api";
import type { Route } from "./route";

const mocks = vi.hoisted(() => ({ loadHistory: vi.fn() }));
vi.mock("./sourcesApi", async (importOriginal) => ({ ...(await importOriginal<typeof import("./sourcesApi")>()), loadHistory: mocks.loadHistory }));

import { useSourceReload } from "./useSourceReload";

const query = { src: "pi", tags: "A,B", start: "2026-01-01T00:00:00Z", end: "2026-01-02T00:00:00Z", period: "60" };
const route: Route = { dataset: "gone", view: "trends", loop: null, sub: "detail", query };
const cache = { id: "gone", source: { kind: "history" } } as unknown as DatasetSummary;

describe("useSourceReload", () => {
  beforeEach(() => mocks.loadHistory.mockReset());

  it("reloads the window and navigates (replace) to the new dataset keeping the query", async () => {
    mocks.loadHistory.mockResolvedValue({ dataset_id: "fresh" });
    const navigate = vi.fn();
    const refresh = vi.fn();
    renderHook(() => useSourceReload(route, [], true, navigate, refresh));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith({ ...route, dataset: "fresh" }, true));
    expect(mocks.loadHistory).toHaveBeenCalledWith("pi", ["A", "B"], { start_utc: query.start, end_utc: query.end }, 60);
    expect(refresh).toHaveBeenCalled();
  });

  it("does nothing while the history cache still exists", () => {
    renderHook(() => useSourceReload(route, [cache], true, vi.fn(), vi.fn()));
    expect(mocks.loadHistory).not.toHaveBeenCalled();
  });

  it("does nothing before the dataset list has loaded", () => {
    renderHook(() => useSourceReload(route, [], false, vi.fn(), vi.fn()));
    expect(mocks.loadHistory).not.toHaveBeenCalled();
  });
});

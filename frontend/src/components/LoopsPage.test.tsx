// Tests of LoopsPage honouring the `mode` query: a link from Overview opens the Live view even when
// no loop has a job, and an absent or unknown mode keeps the old default.
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Route } from "../route";
import { LoopsPage, requestedMode } from "./LoopsPage";

vi.mock("./LiveLoops", () => ({
  LiveLoops: () => <div data-testid="live-loops" />,
  useLiveLoops: () => ({ loops: [{ id: "l1", job: null }] }),
}));
vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  fetchLoops: vi.fn(() => new Promise(() => {})),
}));

const t = (key: string) => key;

function route(query?: Record<string, string>): Route {
  return { dataset: "d", view: "loops", loop: null, sub: "detail", ...(query ? { query } : {}) };
}

describe("requestedMode", () => {
  it("reads live and dataset, ignores anything else", () => {
    expect(requestedMode(route({ mode: "live" }))).toBe("live");
    expect(requestedMode(route({ mode: "dataset" }))).toBe("dataset");
    expect(requestedMode(route({ mode: "bogus" }))).toBeNull();
    expect(requestedMode(route())).toBeNull();
  });
});

describe("LoopsPage", () => {
  const props = { datasetId: "d", navigate: vi.fn(), t, onAnalysed: vi.fn(), tags: [] };

  it("shows the live view for mode=live even without a job", () => {
    render(<LoopsPage {...props} route={route({ mode: "live" })} />);
    expect(screen.getByTestId("live-loops")).toBeTruthy();
  });

  it("falls back to the dataset view when no job runs and no mode is given", () => {
    render(<LoopsPage {...props} route={route()} />);
    expect(screen.queryByTestId("live-loops")).toBeNull();
  });
});

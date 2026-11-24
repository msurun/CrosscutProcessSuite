// Tests of the live loops client: URLs and unwrapping of the loops list.
import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchLiveLoop, fetchLiveLoops } from "./liveLoopsApi";

function stubFetch(body: unknown) {
  const mock = vi.fn(async (_url: string) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } }));
  vi.stubGlobal("fetch", mock);
  return mock;
}

afterEach(() => vi.unstubAllGlobals());

describe("liveLoopsApi", () => {
  it("returns the loops array of the list response", async () => {
    const mock = stubFetch({ loops: [{ id: "a" }] });
    expect(await fetchLiveLoops()).toEqual([{ id: "a" }]);
    expect(mock.mock.calls[0][0]).toBe("/api/live/loops");
  });

  it("encodes the id and passes the limit", async () => {
    const mock = stubFetch({ id: "a/b", history: [] });
    await fetchLiveLoop("a/b", 50);
    expect(mock.mock.calls[0][0]).toBe("/api/live/loops/a%2Fb?limit=50");
  });
});
